from __future__ import annotations

import copy
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import uuid
import zipfile

import nibabel as nib
import numpy as np

APP_VERSION = '0.1.0'
CASE_FIELDS = frozenset('schema_version dataset_version case_key participant_id visit_month original_visit_code source_visit_label knee_side sequence source_series_key series_instance_uid archive_series_number dicom_series_number source_study_date source_series_description dimensions_xyz spacing_xyz_mm origin_lps_mm direction_lps_columns expected_slice_count slice_index_convention image_sha256 annotation_status preparation_verifier'.split())
INDEX_FIELDS = ['participant_id', 'visit_month', 'knee_side', 'case_key', 'relative_folder', 'expected_slice_count', 'annotation_status', 'image_sha256']
SLICE_CONVENTION = 'zero-based along physical volume axis 2; ascending projection on DICOM row-direction cross column-direction; never InstanceNumber'
TOL_MM = 0.01
PRACTICE_ACTORS = {'automated': 'Software QA (automated)',
                   'human_unverified': 'Preview user (identity unverified)'}
PRACTICE_APPROVAL_ROLES = {
    'automated': 'Automated software workflow check only; not a human or anatomical approval',
    'human_unverified': 'Software practice operator; not an accepted research annotation or independent assessment'}



class ValidationError(ValueError):
    """Actionable message safe for the normal application interface."""


def need(condition, message):
    if not condition:
        raise ValidationError(message)


def validate_practice_context(context, protocol):
    """Explicit, immutable software-practice attribution within meniscus_job/1."""
    if context is None:
        return None
    need(isinstance(context, dict) and set(context) == {'purpose', 'actor', 'actor_type'},
         'Software practice context requires purpose, actor and actor_type only.')
    need(context.get('purpose') == 'software_practice' and context.get('actor_type') in PRACTICE_ACTORS,
         'Unsupported software practice purpose or actor type.')
    need(context.get('actor') == PRACTICE_ACTORS[context['actor_type']],
         'Software practice actor must use the canonical non-research role label; do not attribute automated work to Jeff.')
    need(protocol.get('status') == 'draft',
         'Software practice requires a draft protocol and cannot be promoted to research annotation.')
    return copy.deepcopy(context)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValidationError('Cannot read valid metadata: %s. Restore a verified copy.' % Path(path).name) from exc


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def fsync_dir(path):
    if os.name != 'nt':
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        write_json(temporary, value)
        os.replace(str(temporary), str(path))
        fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def safe_relative(root, name):
    relative = PurePosixPath(name)
    need(name and not relative.is_absolute() and '..' not in relative.parts and '\\' not in name,
         'Dataset contains an unsafe relative path.')
    path = Path(root).joinpath(*relative.parts)
    need(within(path, root), 'Dataset path leaves its selected folder.')
    # Do not follow a symlink inside a package, even one that currently stays inside.
    current = path
    while current != Path(root):
        need(not current.is_symlink(), 'Dataset contains a symbolic link. Use a complete local package.')
        current = current.parent
    return path


def case_folder_options(metadata):
    """Canonical source layouts; identities stay in unchanged case metadata.

    Do not infer identity by splitting underscores in a participant ID. Match the
    entire canonical name generated from the explicit metadata instead.
    """
    for field in ('participant_id', 'source_series_key'):
        value = metadata[field]
        need(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value)
             and not value.endswith('.'), 'Case source identity contains an unsafe path component.')
    month = metadata['visit_month']
    need(type(month) is int and 0 <= month <= 999, 'Case visit must be a three-digit nonnegative month.')
    side = {'L': 'LEFT', 'R': 'RIGHT'}.get(metadata['knee_side'])
    need(side is not None, 'Knee side must be explicit in the source metadata.')
    flat = 'Cases/OAI_%s_M%03d_%s' % (metadata['participant_id'], month, side)
    legacy = 'Cases/OAI_%s/M%03d/%s/series_%s' % (metadata['participant_id'], month, side, metadata['source_series_key'])
    return flat, legacy


def max_corner_error(a, b, shape):
    import itertools
    corners = np.array([(*p, 1.) for p in itertools.product(*[(0, n-1) for n in shape])])
    return float(np.linalg.norm((corners @ (a-b).T)[:, :3], axis=1).max())


def check_nifti(path, shape=None, affine_ras=None, integer_labels=False):
    """Validate raw header before a reader chooses a transform. No resampling."""
    try:
        im = nib.load(str(path))
        need(isinstance(im, nib.Nifti1Image), 'Only scalar 3D NIfTI-1 images are supported.')
        need(len(im.shape) == 3 and min(im.shape) > 0, 'Image must be a complete scalar 3D volume.')
        need(shape is None or tuple(im.shape) == tuple(shape), 'Image dimensions differ from the source grid.')
        h = im.header
        need(h.get_xyzt_units()[0] == 'mm', 'NIfTI spatial units must explicitly be millimetres.')
        q, qc = h.get_qform(coded=True)
        s, sc = h.get_sform(coded=True)
        need(int(qc) > 0 and int(sc) > 0, 'NIfTI requires both active qform and sform transforms.')
        need(np.isfinite(q).all() and np.isfinite(s).all(), 'NIfTI contains non-finite geometry.')
        need(max_corner_error(q, s, im.shape) <= TOL_MM, 'NIfTI qform and sform conflict. Obtain a verified source copy.')
        spacing = np.asarray(h.get_zooms()[:3], dtype=float)
        need(np.isfinite(spacing).all() and (spacing > 0).all(), 'NIfTI spacing is invalid.')
        rotation = s[:3, :3] / np.linalg.norm(s[:3, :3], axis=0)
        need(np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5, rtol=0), 'Sheared or irregular image grids are unsupported.')
        need(affine_ras is None or max(max_corner_error(q, affine_ras, im.shape), max_corner_error(s, affine_ras, im.shape)) <= TOL_MM,
             'Image origin, spacing or direction differs from its source geometry.')
        if integer_labels:
            need(np.issubdtype(h.get_data_dtype(), np.integer), 'Label image must use an integer storage type.')
            slope, intercept = im.dataobj.slope, im.dataobj.inter
            need(slope == 1 and intercept == 0, 'Label image must not apply intensity scaling.')
        return im
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError('Cannot read NIfTI image %s. Obtain a verified copy.' % Path(path).name) from exc


class Case:
    def __init__(self, root, row):
        self.folder = safe_relative(root, row['relative_folder'])
        self.image_path = self.folder / 'image.nii.gz'
        for source_path in (self.image_path, self.folder / 'case.json', self.folder / 'slice_review.csv', Path(root) / 'case_index.csv'):
            need(not source_path.is_symlink(), 'Dataset source files must not be symbolic links. Use a complete local package.')
        self._source_hashes = {self.folder / 'case.json': sha256(self.folder / 'case.json'), self.folder / 'slice_review.csv': sha256(self.folder / 'slice_review.csv'), Path(root) / 'case_index.csv': sha256(Path(root) / 'case_index.csv')}
        self.metadata = read_json(self.folder / 'case.json')
        m = self.metadata
        need(set(m) == CASE_FIELDS, 'Unsupported or incomplete case.json schema. An adapter update is required.')
        need(m['schema_version'] == 'meniscus_case/1', 'Unsupported case schema version.')
        self.key = m['case_key']
        need(isinstance(self.key, str) and self.key.strip(), 'Case identity is missing.')
        need(m['sequence'] == 'sagittal IW fat-suppressed TSE', 'Case is not the supported acquired sagittal IWFS sequence.')
        need(m['slice_index_convention'] == SLICE_CONVENTION, 'Unsupported acquired-slice index convention.')
        need(m['knee_side'] in ('L', 'R'), 'Knee side must be explicit in the source metadata.')
        need(m['annotation_status'] == 'not_started', 'Input package must contain original unannotated inputs.')
        need(type(m['visit_month']) is int and m['visit_month'] >= 0, 'Case visit is invalid.')
        need(all(isinstance(m[k], str) and bool(m[k].strip()) for k in ('dataset_version', 'participant_id', 'source_series_key', 'series_instance_uid', 'preparation_verifier')), 'Case source identity is incomplete.')
        need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', m['dataset_version']) and not m['dataset_version'].endswith('.') and m['dataset_version'].upper().split('.')[0] not in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}, 'Dataset version must be a safe portable folder identifier.')
        shape = np.asarray(m['dimensions_xyz'])
        spacing = np.asarray(m['spacing_xyz_mm'], dtype=float)
        origin = np.asarray(m['origin_lps_mm'], dtype=float)
        direction = np.asarray(m['direction_lps_columns'], dtype=float)
        need(shape.shape == (3,) and np.issubdtype(shape.dtype, np.integer) and (shape > 0).all(), 'Invalid source dimensions.')
        need(spacing.shape == (3,) and origin.shape == (3,) and direction.shape == (3, 3), 'Invalid source geometry fields.')
        need(np.isfinite(spacing).all() and (spacing > 0).all() and np.isfinite(origin).all() and np.isfinite(direction).all(), 'Invalid source geometry values.')
        need(np.allclose(direction.T @ direction, np.eye(3), atol=1e-5, rtol=0), 'Source direction is not orthonormal.')
        need(abs(direction[0, 2]) >= np.cos(np.pi/4), 'Acquired slice planes are not supported sagittal planes.')
        self.shape_xyz = tuple(int(v) for v in shape)
        self.n_slices = self.shape_xyz[2]
        need(type(m['expected_slice_count']) is int and m['expected_slice_count'] == self.n_slices, 'Source slice count does not match its native grid.')
        affine_lps = np.eye(4)
        affine_lps[:3, :3] = direction @ np.diag(spacing)
        affine_lps[:3, 3] = origin
        self.affine_ras = np.diag([-1, -1, 1, 1]) @ affine_lps
        for k in ('participant_id', 'knee_side', 'case_key', 'image_sha256', 'annotation_status'):
            need(str(m[k]) == str(row[k]), 'Case index and metadata disagree: ' + k)
        need(int(row['visit_month']) == m['visit_month'] and int(row['expected_slice_count']) == self.n_slices, 'Case index visit or slice count differs.')
        need(row['relative_folder'] in case_folder_options(m), 'Case folder does not match its explicit source identity.')
        self.verify_source()
        with (self.folder / 'slice_review.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == ['slice_index', 'status'], 'Original slice review columns are unsupported.')
            reviews = list(reader)
        need([r['slice_index'] for r in reviews] == [str(k) for k in range(self.n_slices)] and all(r['status'] == 'not_reviewed' for r in reviews), 'Original slice review table is incomplete or modified.')
        self.identity = canonical(m)

    def verify_source(self):
        for path, expected_hash in self._source_hashes.items():
            need(sha256(path) == expected_hash, 'Original source metadata or slice-review table changed (%s). Reconnect a verified original dataset.' % path.name)
        need(sha256(self.image_path) == self.metadata['image_sha256'], 'Source image checksum changed. Reconnect a verified original dataset.')
        check_nifti(self.image_path, self.shape_xyz, self.affine_ras)


class Dataset:
    """Closed adapter for the preparation session's meniscus_case/1 package."""
    def __init__(self, root, progress=None):
        self.root = Path(root).resolve()
        need(self.root.is_dir() and (self.root / 'README.txt').is_file(), 'Select the complete dataset folder containing README.txt and case_index.csv.')
        try:
            with (self.root / 'case_index.csv').open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                need(reader.fieldnames == INDEX_FIELDS, 'Unsupported case index columns. An adapter update is required.')
                rows = list(reader)
            need(rows, 'Dataset case index is empty.')
            self.cases = []
            if progress:
                progress(0, len(rows))
            for row in rows:
                try:
                    self.cases.append(Case(self.root, row))
                    if progress:
                        progress(len(self.cases), len(rows))
                except (ValidationError, OSError, ValueError, TypeError, KeyError) as exc:
                    raise ValidationError('Case %s: %s' % (row.get('case_key', '(unknown)'), exc)) from exc
            need(len({c.key for c in self.cases}) == len(self.cases), 'Dataset has duplicate case identities.')
            need(len({c.metadata['series_instance_uid'] for c in self.cases}) == len(self.cases), 'Dataset repeats a source series.')
            need(len({c.metadata['source_series_key'] for c in self.cases}) == len(self.cases), 'Dataset repeats a source-series key.')
            versions = {c.metadata['dataset_version'] for c in self.cases}
            need(len(versions) == 1, 'Dataset contains conflicting version identifiers.')
            self.version = versions.pop()
            self.identity = canonical(sorted((c.key, c.identity) for c in self.cases))
            self.by_key = {c.key: c for c in self.cases}
        except ValidationError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValidationError('Cannot open a complete dataset. Restore the package and try again.') from exc


class CaseLock:
    """OS advisory lock; process death releases it. Lockfile is never unlinked."""
    def __init__(self, path):
        self.stream = Path(path).open('a+b')
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            self.stream.close()
            raise ValidationError('This case is already open in another application instance. Close it there first.') from exc

    def close(self):
        if self.stream.closed:
            return
        if os.name == 'nt':
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def array_check(labels, uncertainty, case):
    expected = case.shape_xyz[::-1]
    need(tuple(labels.shape) == expected and tuple(uncertainty.shape) == expected, 'Annotation extent must match every voxel of the original source image.')
    need(np.issubdtype(labels.dtype, np.integer) and np.isin(labels, [0, 1, 2]).all(), 'Anatomical labels must be integers: 0 background, 1 medial, 2 lateral.')
    need(np.issubdtype(uncertainty.dtype, np.integer) and np.isin(uncertainty, [0, 1]).all(), 'Uncertainty must be a separate binary image.')


def write_native(path, array_kji, case):
    im = nib.Nifti1Image(np.ascontiguousarray(array_kji.transpose(2, 1, 0), dtype=np.uint8), case.affine_ras)
    im.header.set_xyzt_units('mm')
    im.set_qform(case.affine_ras, code=1)
    im.set_sform(case.affine_ras, code=1)
    nib.save(im, str(path))
    checked = check_nifti(path, case.shape_xyz, case.affine_ras, integer_labels=True)
    need(np.array_equal(np.asarray(checked.dataobj).transpose(2, 1, 0), array_kji), 'Reopened output differs from the in-memory annotation.')


def resolve_starting_mask_path(dataset, starting_mask):
    """Resolve explicit permissions without changing the canonical job dictionary.

    Package-relative paths are anchored to the selected dataset, never CWD.
    Explicit absolute paths remain supported for historical correction jobs.
    """
    name = starting_mask.get('path') if isinstance(starting_mask, dict) else None
    need(isinstance(name, str) and bool(name.strip()), 'Correction job requires an explicit starting-mask path.')
    path = Path(name)
    if path.is_absolute():
        return path.resolve()
    return safe_relative(dataset.root, name)


def validate_job(dataset, job, require_full_correction=False, verify_masks=True, allow_unresolved=False):
    """Read-only job/mask validation; never creates annotation work or approval.

    Generic historical jobs may list only some cases. Prepared correction
    packages must explicitly cover every case, so no omitted rule becomes blank.
    """
    need(isinstance(job, dict) and job.get('schema_version') == 'meniscus_job/1' and job.get('dataset_identity') == dataset.identity, 'Job configuration does not match this dataset.')
    rules = job.get('cases', {})
    need(isinstance(rules, dict) and set(rules).issubset(dataset.by_key), 'Job configuration refers to an unknown case or has invalid case rules.')
    protocol = job.get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
    need(isinstance(protocol, dict) and isinstance(protocol.get('version'), str) and protocol['version'].strip() and protocol.get('status') in ('draft', 'released'), 'Job configuration requires an explicit protocol version and draft/released status.')
    validate_practice_context(job.get('practice_context'), protocol)
    if require_full_correction:
        need('protocol' in job, 'Correction package job requires an explicit documented protocol version and status.')
        need(set(rules) == set(dataset.by_key), 'Correction package job must explicitly list every case; omitted cases cannot default to blank.')
    verified, unresolved = [], []
    for key, rule in rules.items():
        need(isinstance(rule, dict) and rule.get('annotation_mode', 'blank') in ('blank', 'correction'), 'Job configuration has an invalid annotation mode.')
        if require_full_correction:
            need(rule.get('annotation_mode') == 'correction', 'Correction package job must explicitly select correction for every case.')
        availability = rule.get('availability', 'ready')
        need(availability in ('ready', 'unresolved'), 'Correction job availability is invalid.')
        if rule.get('annotation_mode', 'blank') == 'blank':
            need(availability == 'ready', 'An unavailable prediction cannot silently become blank annotation.')
            need(rule.get('starting_mask') is None, 'Prediction-free case rules must not include a starting mask.')
            continue
        if availability == 'unresolved':
            need('starting_mask' in rule and rule['starting_mask'] is None and isinstance(rule.get('reason'), str) and rule['reason'].strip(), 'Unresolved correction cases require an explicit reason and no fabricated starting mask.')
            unresolved.append({'case_key': key, 'reason': rule['reason']})
            continue
        start = rule.get('starting_mask')
        need(isinstance(start, dict) and all(isinstance(start.get(k), str) and start[k].strip() for k in ('path', 'sha256', 'version', 'source')), 'Correction job requires an explicitly permitted mask path, checksum, source and version.')
        # Resolve even metadata-only validation so unsafe package paths fail early.
        original = resolve_starting_mask_path(dataset, start)
        if verify_masks:
            need(original.is_file(), 'Permitted starting mask is unavailable. Restore the verified correction input; this case cannot become blank annotation.')
            need(sha256(original) == start['sha256'], 'Permitted starting mask checksum does not match the job.')
            case = dataset.by_key[key]
            image = check_nifti(original, case.shape_xyz, case.affine_ras, True)
            labels = np.asarray(image.dataobj).transpose(2, 1, 0)
            array_check(labels, np.zeros(case.shape_xyz[::-1], dtype=np.uint8), case)
            verified.append({'case_key': key, 'sha256': start['sha256'], 'label_values': [int(v) for v in np.unique(labels)], 'native_grid_verified': True})
    need(allow_unresolved or not unresolved, 'Correction package is incomplete: an automated starting prediction is unresolved. It cannot default to blank annotation.')
    correction_count = sum(rule.get('annotation_mode') == 'correction' for rule in rules.values())
    complete = set(rules) == set(dataset.by_key) and correction_count == len(dataset.cases) and not unresolved and len(verified) == len(dataset.cases)
    return {'dataset_identity': dataset.identity, 'listed_cases': len(rules), 'correction_cases': correction_count, 'verified_masks': len(verified), 'unresolved_cases': len(unresolved), 'correction_package_complete': complete, 'require_full_correction': require_full_correction, 'masks': verified, 'unresolved': unresolved}


def load_job_config(path, dataset, require_full_correction=False, allow_unresolved=False):
    """Load an explicit job unchanged, validating relative paths against dataset."""
    job = read_json(path)
    validate_job(dataset, job, require_full_correction=require_full_correction, allow_unresolved=allow_unresolved)
    return job


def correction_inputs_present(dataset):
    return any((case.folder / name).exists() or (case.folder / name).is_symlink()
               for case in dataset.cases for name in ('starting_mask.nii.gz', 'starting_mask.json'))


def load_dataset_job_config(dataset, remembered_path=None, fixed_job_path=None):
    """Resolve the existing UI's job choice without a blank correction fallback.

    Fixed software-practice launchers retain their immutable explicit job. In an
    ordinary correction package, a remembered job must also cover every case in
    correction mode; a stale blank/partial job cannot override package intent.
    """
    if fixed_job_path is not None:
        fixed_job = load_job_config(fixed_job_path, dataset, allow_unresolved=True)
        need(isinstance(fixed_job.get('practice_context'), dict) and fixed_job['practice_context'].get('purpose') == 'software_practice', 'Fixed software-practice configuration requires its explicit software-practice actor and protocol.')
        return fixed_job, str(fixed_job_path)
    package_job = dataset.root / 'correction_job.json'
    packaged = package_job.exists() or package_job.is_symlink()
    need(not package_job.is_symlink(), 'Package correction configuration must not be a symbolic link.')
    has_masks = correction_inputs_present(dataset)
    chosen = str(remembered_path) if remembered_path else (str(package_job) if packaged else None)
    need(chosen is not None or not has_masks, 'Starting-mask files are present but correction_job.json is missing. Restore the explicit correction permissions; this package cannot default to blank annotation.')
    if chosen is None:
        return None, None
    require_full = packaged or has_masks or Path(chosen).name == 'correction_job.json'
    return load_job_config(chosen, dataset, require_full_correction=require_full, allow_unresolved=True), chosen


def require_case_prediction_available(job, case_key):
    rule = (job or {}).get('cases', {}).get(case_key, {})
    need(rule.get('availability', 'ready') != 'unresolved', 'Starting automated mask is unresolved for this scan: ' + str(rule.get('reason', 'No technically verified starting mask is available.')) + ' This case is blocked; no blank annotation was created.')


class WorkStore:
    def __init__(self, root, dataset, job=None):
        self.root = Path(root).resolve()
        self.dataset = dataset
        need(not within(self.root, dataset.root) and not within(dataset.root, self.root), 'Work folder must be separate from the original dataset.')
        need('dropbox' not in str(self.root).lower() and 'cloudstorage' not in str(self.root).lower() and 'onedrive' not in str(self.root).lower(), 'Choose a local work folder outside live cloud sync folders.')
        self.root.mkdir(parents=True, exist_ok=True)
        self.job = copy.deepcopy(job)
        if self.job is not None:
            validate_job(dataset, self.job, verify_masks=False, allow_unresolved=True)
        protocol = (self.job or {}).get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
        self.practice_context = validate_practice_context((self.job or {}).get('practice_context'), protocol)
        binding_path = self.root / 'dataset.json'
        binding = {'schema_version': 'meniscus_work/1', 'dataset_identity': dataset.identity, 'dataset_version': dataset.version}
        if self.practice_context is not None:
            binding['practice_context'] = copy.deepcopy(self.practice_context)
        # Claim only a previously empty/unclaimed folder; no overwrite of other datasets or practice scopes.
        if binding_path.exists():
            need(read_json(binding_path) == binding, 'Work folder belongs to a different dataset or practice scope. Reconnect the original configuration or choose a separate local work folder.')
        else:
            write_json(binding_path, binding)
        self.cases_root = self.root / 'cases'
        self.cases_root.mkdir(exist_ok=True)

    def case_folder(self, case):
        return self.cases_root / hashlib.sha256(case.key.encode()).hexdigest()[:24]

    def open_case(self, case):
        need(case.key in self.dataset.by_key and self.dataset.by_key[case.key].identity == case.identity, 'Case does not belong to this dataset.')
        require_case_prediction_available(self.job, case.key)
        return CaseSession(self, case)

    def summary(self, case):
        folder = self.case_folder(case)
        for checkpoint in self._checkpoints(folder):
            try:
                state = self._validate_checkpoint(checkpoint, case, read_arrays=False)[0]
                return {'status': state['status'], 'reviewed': sum(r['reviewed'] for r in state['review']), 'flagged': sum(r['flag'] for r in state['review']), 'checkpoint': checkpoint.name, 'last_slice': state['last_slice']}
            except (ValidationError, OSError, KeyError, ValueError):
                continue
        return {'status': 'not_started', 'reviewed': 0, 'flagged': 0, 'last_slice': 0, 'checkpoint': None}

    def _checkpoints(self, folder):
        versions = folder / 'versions'
        if not versions.exists():
            return []
        # Directories named .pending-* are never candidates, even after a crash.
        return sorted((p for p in versions.iterdir() if p.is_dir() and p.name.startswith('v-')), reverse=True)

    def _validate_checkpoint(self, path, case, read_arrays=True):
        manifest = read_json(path / 'manifest.json')
        need(manifest.get('schema_version') == 'meniscus_checkpoint/1' and manifest.get('source_identity') == case.identity and manifest.get('source_image_sha256') == case.metadata['image_sha256'], 'Saved checkpoint source identity is mismatched.')
        expected = {'annotation.json', 'slice_review.csv', 'labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz', 'segmentation.seg.nrrd'}
        need(set(manifest.get('files_sha256', {})) == expected, 'Saved checkpoint is incomplete.')
        for name, digest in manifest['files_sha256'].items():
            need(sha256(path / name) == digest, 'Saved checkpoint is corrupt: ' + name)
        state = read_json(path / 'annotation.json')
        self._validate_state(state, case)
        with (path / 'slice_review.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == ['slice_index', 'displayed_slice', 'status', 'attention_flag', 'note'], 'Saved review CSV has unsupported columns.')
            rows = list(reader)
        expected_review = [{'slice_index': str(r['slice_index']), 'displayed_slice': str(r['slice_index']+1), 'status': 'reviewed' if r['reviewed'] else 'not_reviewed', 'attention_flag': str(int(r['flag'])), 'note': r.get('note', '')} for r in state['review']]
        need(rows == expected_review, 'Saved review CSV disagrees with annotation metadata.')
        if not read_arrays:
            return state, None, None
        arrays = []
        for name in ('labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz'):
            im = check_nifti(path / name, case.shape_xyz, case.affine_ras, True)
            arrays.append(np.asarray(im.dataobj).transpose(2, 1, 0).copy())
        labels, uncertainty, validity = arrays
        array_check(labels, uncertainty, case)
        if state['status'] in ('approved', 'practice_approved'):
            need(not uncertainty.any(), 'Approved work contains unresolved uncertain voxels.')
        expected_valid = validity_array(state, uncertainty)
        need(np.array_equal(validity, expected_valid), 'Training validity image disagrees with review or uncertainty records.')
        return state, labels, uncertainty

    def _validate_state(self, state, case):
        need(state.get('app_version') == APP_VERSION, 'Saved work uses a different application version. Use the fixed batch version or an explicitly tested migration.')
        need(state.get('schema_version') == 'meniscus_annotation/1' and state.get('source_identity') == case.identity and state.get('dataset_identity') == self.dataset.identity, 'Saved annotation belongs to a different scan or dataset.')
        need(state.get('label_mapping') == {'0': 'background', '1': 'medial meniscus', '2': 'lateral meniscus'}, 'Saved label mapping is invalid.')
        need(state.get('source_image_sha256') == case.metadata['image_sha256'] and state.get('source') == case.metadata and state.get('case_key') == case.key, 'Saved source metadata or checksum is inconsistent.')
        need(state.get('initialization', {}).get('method') in ('blank', 'correction'), 'Saved initialization mode is invalid.')
        need(state.get('protocol', {}).get('version') and state.get('protocol', {}).get('status') in ('draft', 'released'), 'Saved annotation protocol is invalid.')
        need(set(state.get('compartments', {})) == {'medial', 'lateral'} and all(type(v) is bool for v in state['compartments'].values()), 'Saved compartment consideration records are invalid.')
        need(isinstance(state.get('notes'), str) and isinstance(state.get('annotator'), str) and state['annotator'].strip(), 'Saved annotator or notes fields are invalid.')
        context = state.get('practice_context')
        need(context == self.practice_context, 'Saved software practice context differs from the explicit job configuration.')
        expected_actor = context['actor'] if context is not None else 'Jeff'
        need(state['annotator'] == expected_actor, 'Saved annotation actor differs from its assigned research or software-practice role.')
        if context is not None:
            validate_practice_context(context, state['protocol'])
            need(state['protocol'] == (self.job or {}).get('protocol', {'version': 'draft-practice-1', 'status': 'draft'}), 'Saved software practice protocol differs from the explicit job configuration.')
            need(state.get('annotation_purpose') == 'software_practice' and state.get('status') != 'approved', 'Software practice cannot be an accepted research annotation.')
        reviews = state.get('review', [])
        need(len(reviews) == case.n_slices and all(r.get('slice_index') == k and type(r.get('reviewed')) is bool and type(r.get('flag')) is bool and isinstance(r.get('note'), str) for k, r in enumerate(reviews)), 'Saved slice review records are incomplete.')
        need(type(state.get('last_slice')) is int and 0 <= state['last_slice'] < case.n_slices, 'Saved slice position is invalid.')
        need(state.get('status') in ('in_progress', 'needs_review', 'approved', 'practice_approved'), 'Saved annotation status is invalid.')
        initialization = state['initialization']
        if initialization['method'] == 'blank':
            need(initialization.get('starting_mask') is None, 'Blank annotation must not contain a starting prediction.')
        else:
            start = initialization.get('starting_mask')
            need(isinstance(start, dict) and all(isinstance(start.get(k), str) and start[k] for k in ('source', 'version', 'sha256')), 'Correction annotation lacks starting-mask provenance.')
        if state['status'] in ('approved', 'practice_approved'):
            approval = state.get('approval')
            need(isinstance(approval, dict) and state.get('approver') == expected_actor and bool(approval.get('approved_utc')), 'Saved approval metadata is incomplete.')
            need(type(approval.get('practice_only')) is bool and approval['practice_only'] == (state['status'] == 'practice_approved'), 'Approval practice status is inconsistent.')
            need(all(r['reviewed'] and not r['flag'] for r in reviews) and all(state['compartments'].values()), 'Approved work has incomplete review or compartment consideration.')
            need(state['status'] != 'approved' or state['protocol']['status'] == 'released', 'Research approval requires a released protocol.')
            if context is not None:
                automated = context['actor_type'] == 'automated'
                need(approval.get('approval_type') == ('automated_software_check' if automated else 'manual_software_practice') and approval.get('role') == PRACTICE_APPROVAL_ROLES[context['actor_type']], 'Software practice approval roles are misleading or incomplete.')
                need(approval.get('human_anatomical_approval') is False and approval.get('accepted_research_annotation') is False and approval.get('deliberate_approval_required_by_ui') is (not automated), 'Software practice approval must not imply a human or research approval.')
        else:
            need(state.get('approval') is None and state.get('approver') is None, 'Draft work must not retain active approval metadata.')


def validity_array(state, uncertainty):
    context = state.get('practice_context')
    if isinstance(context, dict) and context.get('purpose') == 'software_practice':
        # Software review flags exercise workflow only; they never confirm anatomy/background.
        return np.zeros_like(uncertainty, dtype=np.uint8)
    valid_slices = np.asarray([r['reviewed'] and not r['flag'] for r in state['review']], dtype=np.uint8)
    return ((valid_slices[:, None, None] == 1) & (uncertainty == 0)).astype(np.uint8)


class CaseSession:
    def __init__(self, store, case):
        require_case_prediction_available(store.job, case.key)
        self.store, self.case = store, case
        self.folder = store.case_folder(case)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = CaseLock(self.folder / 'case.lock')
        self.closed = False
        self.recovered = False
        self.current_checkpoint = None
        try:
            case.verify_source()
            self.state = self._new_state()
            self._loaded = None
            candidates = store._checkpoints(self.folder)
            for candidate in candidates:
                try:
                    state, labels, uncertainty = store._validate_checkpoint(candidate, case)
                except (ValidationError, OSError, KeyError, ValueError):
                    continue
                need(state.get('job_identity') == self.state.get('job_identity') and state['initialization']['method'] == self.state['initialization']['method'], 'Saved initialization permissions differ from the current job configuration. Reopen with the original explicit job or use a separate work folder.')
                self.state = state
                self._loaded = (labels, uncertainty, candidate / 'segmentation.seg.nrrd')
                self.current_checkpoint = candidate
                self.recovered = candidate != candidates[0]
                break
            need(not candidates or self._loaded is not None, 'No intact saved version could be recovered. Preserve this work folder and restore a backup.')
        except Exception:
            self.close()
            raise

    def _new_state(self):
        job = self.store.job or {}
        require_case_prediction_available(job, self.case.key)
        rule = job.get('cases', {}).get(self.case.key, {})
        mode = rule.get('annotation_mode', 'blank')
        need(mode in ('blank', 'correction'), 'Unsupported annotation mode in explicit job configuration.')
        protocol = job.get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
        need(protocol.get('version') and protocol.get('status') in ('draft', 'released'), 'Job protocol version/status is invalid.')
        return {'schema_version': 'meniscus_annotation/1', 'app_version': APP_VERSION,
                'dataset_identity': self.store.dataset.identity, 'source_identity': self.case.identity,
                'source_image_sha256': self.case.metadata['image_sha256'], 'case_key': self.case.key,
                'source': copy.deepcopy(self.case.metadata), 'label_mapping': {'0': 'background', '1': 'medial meniscus', '2': 'lateral meniscus'},
                'array_convention': 'files IJK; application arrays KJI; displayed slice n = stored k + 1',
                'review': [{'slice_index': k, 'reviewed': False, 'flag': False, 'note': ''} for k in range(self.case.n_slices)],
                'notes': '', 'compartments': {'medial': False, 'lateral': False}, 'protocol': copy.deepcopy(protocol),
                'practice_context': copy.deepcopy(self.store.practice_context),
                'annotation_purpose': 'software_practice' if self.store.practice_context is not None else 'research_annotation',
                'annotator': self.store.practice_context['actor'] if self.store.practice_context is not None else 'Jeff', 'approver': None, 'approval': None,
                'initialization': {'method': mode, 'starting_mask': None}, 'job_identity': canonical(job) if job else None,
                'last_slice': 0, 'status': 'in_progress', 'created_utc': now(), 'saved_utc': None,
                'uncertainty_policy': 'Separate binary overlay may overlap anatomical labels; all uncertainty and attention flags must be resolved before approval. ' + ('SOFTWARE PRACTICE validity is zero for every voxel; review flags do not confirm anatomical labels or background.' if self.store.practice_context is not None else 'Training validity excludes uncertain and unreviewed/flagged voxels.'),
                'technical_acceptance_scope': 'Identity, byte integrity, native geometry, label mapping and review completeness only; not anatomical correctness. Downstream training-loader integration is a separate requirement.'}

    def blank_arrays(self):
        return (np.zeros(self.case.shape_xyz[::-1], dtype=np.uint8), np.zeros(self.case.shape_xyz[::-1], dtype=np.uint8))

    def load(self):
        if self._loaded is not None:
            return self._loaded[0].copy(), self._loaded[1].copy(), self._loaded[2]
        labels, uncertainty = self.blank_arrays()
        if self.state['initialization']['method'] == 'correction':
            rule = self.store.job['cases'][self.case.key]
            start = rule.get('starting_mask', {})
            need(all(start.get(k) for k in ('path', 'sha256', 'version', 'source')), 'Correction mode requires an explicitly permitted starting mask with source, version and checksum.')
            original = resolve_starting_mask_path(self.store.dataset, start)
            need(original.is_file(), 'Permitted starting mask is unavailable. Restore the verified correction input; this case cannot become blank annotation.')
            need(sha256(original) == start['sha256'], 'Permitted starting mask checksum does not match the job.')
            im = check_nifti(original, self.case.shape_xyz, self.case.affine_ras, True)
            labels = np.asarray(im.dataobj).transpose(2, 1, 0).copy()
            array_check(labels, uncertainty, self.case)
            preserved = self.folder / ('starting-mask-' + start['sha256'] + '.nii.gz')
            if preserved.exists():
                need(sha256(preserved) == start['sha256'], 'Preserved starting mask is corrupt.')
            else:
                temporary = preserved.with_suffix('.tmp')
                try:
                    shutil.copyfile(original, temporary)
                    need(sha256(temporary) == start['sha256'], 'Starting mask changed while copying.')
                    os.replace(temporary, preserved)
                finally:
                    temporary.unlink(missing_ok=True)
            self.state['initialization']['starting_mask'] = {k: start[k] for k in ('source', 'version', 'sha256')}
        self._loaded = (labels.copy(), uncertainty.copy(), None)
        return labels, uncertainty, None

    def mark_changed(self, indices):
        need(not self.closed, 'This case session is closed.')
        for index in indices:
            need(0 <= int(index) < self.case.n_slices, 'Changed slice is outside the acquired volume.')
            self.state['review'][int(index)]['reviewed'] = False
        self.state['status'] = 'needs_review'
        self.state['approval'] = None
        self.state['approver'] = None

    def approval_errors(self, labels, uncertainty, practice=False):
        errors = []
        try:
            array_check(labels, uncertainty, self.case)
        except ValidationError as exc:
            errors.append(str(exc))
            return errors
        if not all(r['reviewed'] for r in self.state['review']):
            errors.append('Explicitly review every acquired slice, including empty slices.')
        if any(r['flag'] for r in self.state['review']) or uncertainty.any():
            errors.append('Resolve all attention flags and uncertain voxels before approval.')
        if not all(self.state['compartments'].get(k) is True for k in ('medial', 'lateral')):
            errors.append('Confirm that both medial and lateral compartments were considered.')
        if not self.state.get('annotator') or not self.state['protocol'].get('version'):
            errors.append('Record the annotator and annotation protocol version.')
        if self.store.practice_context is not None and not practice:
            errors.append('SOFTWARE PRACTICE cannot receive research approval. Use separate practice approval/export only.')
        if self.state['protocol'].get('status') != 'released' and not practice:
            errors.append('The anatomical protocol is draft. Only clearly marked practice approval is permitted.')
        return errors

    def save(self, labels, uncertainty, seg_writer, approve=False, practice=False):
        need(not self.closed, 'This case session is closed.')
        self.case.verify_source()
        if self.state['initialization']['method'] == 'correction' and self.state['initialization']['starting_mask'] is None:
            self.load()
        array_check(labels, uncertainty, self.case)
        if approve:
            errors = self.approval_errors(labels, uncertainty, practice)
            need(not errors, ' '.join(errors))
        # Editing previously approved content always creates a new draft checkpoint.
        state = copy.deepcopy(self.state)
        if not approve and state['status'] in ('approved', 'practice_approved'):
            state.update(status='needs_review', approval=None, approver=None)
        state['saved_utc'] = now()
        state['app_version'] = APP_VERSION
        if approve:
            if self.store.practice_context is not None:
                context = self.store.practice_context
                automated = context['actor_type'] == 'automated'
                state.update(status='practice_approved', approver=context['actor'],
                             approval={'approved_utc': now(), 'role': PRACTICE_APPROVAL_ROLES[context['actor_type']],
                                       'practice_only': True, 'approval_type': 'automated_software_check' if automated else 'manual_software_practice',
                                       'human_anatomical_approval': False, 'accepted_research_annotation': False,
                                       'deliberate_approval_required_by_ui': not automated})
            else:
                state.update(status='practice_approved' if practice else 'approved', approver='Jeff',
                             approval={'approved_utc': now(), 'role': 'assigned annotator and approver; not an independent second reader', 'practice_only': bool(practice), 'deliberate_approval_required_by_ui': True})
        elif state['status'] not in ('in_progress', 'needs_review'):
            state['status'] = 'in_progress'
        self.store._validate_state(state, self.case)
        configured_protocol = (self.store.job or {}).get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
        need(state['protocol'] == configured_protocol, 'Annotation protocol must match the explicit job configuration.')
        versions = self.folder / 'versions'
        versions.mkdir(exist_ok=True)
        checkpoint_id = 'v-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
        pending = versions / ('.pending-' + uuid.uuid4().hex)
        final = versions / checkpoint_id
        try:
            # Conservative minimum before streaming output; actual errors still caught.
            need(shutil.disk_usage(versions).free >= max(16 * 1024 * 1024, labels.nbytes * 5), 'Insufficient free disk space. Free space or choose another local work folder.')
            pending.mkdir()
            write_native(pending / 'labels.nii.gz', labels, self.case)
            write_native(pending / 'uncertainty.nii.gz', uncertainty, self.case)
            write_native(pending / 'validity.nii.gz', validity_array(state, uncertainty), self.case)
            seg_path = pending / 'segmentation.seg.nrrd'
            need(seg_writer(seg_path) is not False and seg_path.is_file() and seg_path.stat().st_size > 0, 'Editable segmentation could not be saved. Retry Save before leaving this case.')
            write_json(pending / 'annotation.json', state)
            with (pending / 'slice_review.csv').open('x', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['slice_index', 'displayed_slice', 'status', 'attention_flag', 'note'])
                writer.writeheader()
                writer.writerows({'slice_index': r['slice_index'], 'displayed_slice': r['slice_index']+1, 'status': 'reviewed' if r['reviewed'] else 'not_reviewed', 'attention_flag': int(r['flag']), 'note': r.get('note', '')} for r in state['review'])
                stream.flush()
                os.fsync(stream.fileno())
            names = ['annotation.json', 'slice_review.csv', 'labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz', 'segmentation.seg.nrrd']
            manifest = {'schema_version': 'meniscus_checkpoint/1', 'checkpoint': checkpoint_id, 'source_identity': self.case.identity,
                        'source_image_sha256': self.case.metadata['image_sha256'], 'files_sha256': {n: sha256(pending / n) for n in names},
                        'technical_checks': 'All NIfTI outputs reopened with nibabel and compared voxel-for-voxel to in-memory KJI arrays; full grid and qform/sform checked.'}
            write_json(pending / 'manifest.json', manifest)
            # Sync all payloads, including Slicer-written segmentation, before commit.
            for child in pending.iterdir():
                with child.open('r+b') as stream:
                    os.fsync(stream.fileno())
            self.store._validate_checkpoint(pending, self.case)
            self.case.verify_source()
            fsync_dir(pending)
            os.replace(pending, final)
            fsync_dir(versions)
            # CURRENT is a convenience. Recovery scans complete immutable checkpoints.
            atomic_json(self.folder / 'CURRENT.json', {'checkpoint': checkpoint_id})
            self.state = state
            self.current_checkpoint = final
            self._loaded = (labels.copy(), uncertainty.copy(), final / 'segmentation.seg.nrrd')
            return final
        except OSError as exc:
            raise ValidationError('Save failed (%s). Check free disk space and write permission. The previous saved version is intact; retry before switching cases.' % (exc.strerror or 'disk error')) from exc
        finally:
            if pending.exists():
                shutil.rmtree(pending, ignore_errors=True)

    def close(self):
        if not getattr(self, 'closed', True):
            self.lock.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def export_approved(store, destination, case_keys=None, include_practice=False):
    """Immutable, verified ZIP. No source MRI. Selected unfinished cases are errors."""
    destination = Path(destination).resolve()
    need(not within(destination, store.dataset.root) and not within(destination, store.root), 'Choose a results folder outside the dataset and active work folder.')
    destination.mkdir(parents=True, exist_ok=True)
    selected = list(case_keys) if case_keys is not None else list(store.dataset.by_key)
    need(len(selected) == len(set(selected)) and all(k in store.dataset.by_key for k in selected), 'Export selection contains unknown or duplicate cases.')
    accepted = []
    for key in selected:
        case = store.dataset.by_key[key]
        case.verify_source()
        # Export most recent preserved approved version, even if a later draft exists.
        found = None
        for checkpoint in store._checkpoints(store.case_folder(case)):
            try:
                state, labels, uncertainty = store._validate_checkpoint(checkpoint, case)
                allowed = ('approved', 'practice_approved') if include_practice else ('approved',)
                if state['status'] not in allowed:
                    continue
                expected_job = canonical(store.job) if store.job else None
                need(state.get('job_identity') == expected_job, 'Saved approval uses a different job configuration. Supply the original explicit job before export.')
                need(all(r['reviewed'] and not r['flag'] for r in state['review']) and not uncertainty.any(), 'Approval review/uncertainty records are incomplete.')
                need(all(state['compartments'].get(k) is True for k in ('medial', 'lateral')), 'Approval compartment records are incomplete.')
                need(state.get('approval') and state.get('approver') == state.get('annotator'), 'Approval metadata or actor attribution is missing.')
                need(state['status'] == 'practice_approved' or state['protocol'].get('status') == 'released', 'Research approval requires a released protocol.')
                found = (case, checkpoint, state)
                break
            except (ValidationError, OSError, ValueError, KeyError) as exc:
                # A corrupt approved version must not be silently substituted.
                raise ValidationError('Case %s cannot be exported: %s Restore an intact saved version.' % (key, exc)) from exc
        if found:
            accepted.append(found)
        elif case_keys is not None:
            raise ValidationError('Case %s has no eligible approved version. Complete review and approval, or remove it from this export.' % key)
    need(accepted, 'No eligible approved cases are available to export.')
    practice = any(s['status'] == 'practice_approved' for _, _, s in accepted)
    software_practice = any(s.get('practice_context') is not None for _, _, s in accepted)
    prefix = 'SOFTWARE_PRACTICE_ONLY-' if software_practice else ('PRACTICE_ONLY-' if practice else '')
    result_name = prefix + 'Meniscus_results_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex[:6] + '.zip'
    output = destination / result_name
    temporary = destination / ('.pending-' + uuid.uuid4().hex + '.zip')
    try:
        receipts = []
        with zipfile.ZipFile(temporary, 'x', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for case, checkpoint, state in accepted:
                export_key = hashlib.sha256(case.key.encode()).hexdigest()[:24]
                payload_names = sorted(read_json(checkpoint / 'manifest.json')['files_sha256']) + ['manifest.json']
                for name in payload_names:
                    archive.write(checkpoint / name, 'cases/' + export_key + '/' + name)
                init = state['initialization'].get('starting_mask')
                if init:
                    original = store.case_folder(case) / ('starting-mask-' + init['sha256'] + '.nii.gz')
                    need(sha256(original) == init['sha256'], 'Case %s preserved starting mask is missing or corrupt.' % case.key)
                    archive.write(original, 'cases/' + export_key + '/original-starting-mask.nii.gz')
                receipts.append({'case_key': case.key, 'folder': 'cases/' + export_key, 'checkpoint': checkpoint.name,
                                 'source_identity': case.identity, 'source_image_sha256': case.metadata['image_sha256'],
                                 'manifest_sha256': sha256(checkpoint / 'manifest.json'), 'status': state['status']})
            manifest = {'schema_version': 'meniscus_results/1', 'created_utc': now(), 'app_version': APP_VERSION,
                        'dataset_identity': store.dataset.identity, 'dataset_version': store.dataset.version,
                        'practice_only': practice, 'software_practice': software_practice, 'cases': receipts,
                        'training_contract': 'labels 0/1/2 fixed background/medial/lateral; use validity.nii.gz to interpret background. Uncertainty is separate, never a third training class.',
                        'limits': 'Technical acceptance is not anatomical validation. Actor roles are recorded per case. Actual downstream training-loader integration must be checked separately.'}
            if software_practice:
                manifest.update(practice_context=copy.deepcopy(store.practice_context), accepted_research_annotation=False, human_anatomical_approval=False)
                manifest['training_contract'] += ' SOFTWARE PRACTICE: validity is zero across the entire grid; no voxel is confirmed training anatomy or background.'
            archive.writestr('results.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', ('SOFTWARE PRACTICE — NOT ACCEPTED RESEARCH ANNOTATIONS; NOT HUMAN ANATOMICAL APPROVAL\nEvery validity voxel is zero. Review flags exercise software only; labels/background are not anatomically confirmed.\n' if software_practice else ('PRACTICE ONLY — NOT RESEARCH APPROVAL\n' if practice else '')) + 'Versioned approved annotations on the original full acquired grid. MRI images are omitted.\nlabels.nii.gz: 0 background, 1 medial, 2 lateral. uncertainty.nii.gz: binary uncertainty.\nOnly voxels with validity.nii.gz = 1 may be treated as reviewed known labels/background.\nTechnical validation does not establish anatomical correctness.\n')
        with zipfile.ZipFile(temporary) as archive:
            need(archive.testzip() is None, 'Export ZIP integrity check failed. Retry export.')
            for case, checkpoint, state in accepted:
                export_key = hashlib.sha256(case.key.encode()).hexdigest()[:24]
                base = 'cases/' + export_key + '/'
                checkpoint_manifest = json.loads(archive.read(base + 'manifest.json'))
                need(hashlib.sha256(archive.read(base + 'manifest.json')).hexdigest() == sha256(checkpoint / 'manifest.json'), 'Case %s exported manifest does not match its saved approval.' % case.key)
                checks = dict(checkpoint_manifest['files_sha256'])
                start = state['initialization'].get('starting_mask')
                if start:
                    checks['original-starting-mask.nii.gz'] = start['sha256']
                for name, expected_hash in checks.items():
                    digest = hashlib.sha256()
                    with archive.open(base + name) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                    need(digest.hexdigest() == expected_hash, 'Case %s exported %s failed its output checksum. Retry export from an intact saved version.' % (case.key, name))
                case.verify_source()
        with temporary.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        fsync_dir(destination)
        return output
    except OSError as exc:
        raise ValidationError('Export failed (%s). Check results folder permission and free disk space, then retry.' % (exc.strerror or 'disk error')) from exc
    finally:
        temporary.unlink(missing_ok=True)
