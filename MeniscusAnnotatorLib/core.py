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

from .correction_resolutions import resolve_registry

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
         'Software practice actor must use the canonical non-research role label; automated checks cannot be attributed to a reader.')
    need(protocol.get('status') == 'draft',
         'Software practice requires a draft protocol and cannot be promoted to research annotation.')
    return copy.deepcopy(context)


def assigned_annotator(job=None):
    """Return an explicit job actor, or None when a local assignment is needed.

    An absent assignment never identifies the person operating the application.
    Legacy checkpoint actors are preserved and checked against an explicitly
    selected local reader by WorkStore, rather than supplied by a default name.
    """
    job = job or {}
    if 'annotator' in job:
        need(isinstance(job['annotator'], str) and bool(job['annotator'].strip()),
             'Job annotator must be an explicitly named, nonempty reader.')
    context = job.get('practice_context')
    if context is not None:
        need(isinstance(context, dict) and isinstance(context.get('actor'), str)
             and bool(context['actor'].strip()), 'Software practice actor is missing.')
        return context['actor']
    return job.get('annotator')


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


class BoundCorrectionJob(dict):
    """Effective UI permissions with an explicit, unchanged base job identity.

    canonical(self) still hashes these effective permissions normally. Saved
    work instead records base_job_identity plus its separate case resolution.
    This object is never serialized over the original source job.
    """
    def __init__(self, effective, source_job, bindings):
        super().__init__(copy.deepcopy(effective))
        self.source_job = copy.deepcopy(source_job)
        self.base_job_identity = canonical(source_job)
        self.resolution_bindings = copy.deepcopy(bindings)


def bind_correction_resolutions(dataset, job):
    """Verify additive permissions and expose them to the unchanged interface."""
    if job is None:
        return None
    need(isinstance(job, dict), 'Job configuration must be a dictionary.')
    source = job.source_job if isinstance(job, BoundCorrectionJob) else job
    need(isinstance(source, dict) and source.get('schema_version') == 'meniscus_job/1'
         and source.get('dataset_identity') == dataset.identity and isinstance(source.get('cases', {}), dict),
         'Job configuration does not match this dataset or has invalid case rules.')
    cases = {case.key: {'metadata': case.metadata, 'relative_folder': case.folder.relative_to(dataset.root).as_posix()}
             for case in dataset.cases}
    effective_rules, bindings, _ = resolve_registry(dataset.root, source, dataset.identity, cases, need, sha256, read_json)
    effective = copy.deepcopy(source)
    if effective_rules:
        effective.setdefault('cases', {}).update(effective_rules)
    if isinstance(job, BoundCorrectionJob):
        need(job.base_job_identity == canonical(source) and dict(job) == effective and job.resolution_bindings == bindings,
             'Correction resolution changed after this job was loaded. Preserve saved work and reconnect the original resolution; permissions were not silently replaced.')
    return BoundCorrectionJob(effective, source, bindings) if bindings else copy.deepcopy(source)


def validate_job(dataset, job, require_full_correction=False, verify_masks=True, allow_unresolved=False):
    """Read-only job/mask validation; never creates annotation work or approval.

    Generic historical jobs may list only some cases. Prepared correction
    packages must explicitly cover every case, so no omitted rule becomes blank.
    """
    job = bind_correction_resolutions(dataset, job)
    need(isinstance(job, dict) and job.get('schema_version') == 'meniscus_job/1' and job.get('dataset_identity') == dataset.identity, 'Job configuration does not match this dataset.')
    rules = job.get('cases', {})
    need(isinstance(rules, dict) and set(rules).issubset(dataset.by_key), 'Job configuration refers to an unknown case or has invalid case rules.')
    protocol = job.get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
    need(isinstance(protocol, dict) and isinstance(protocol.get('version'), str) and protocol['version'].strip() and protocol.get('status') in ('draft', 'released'), 'Job configuration requires an explicit protocol version and draft/released status.')
    validate_practice_context(job.get('practice_context'), protocol)
    assigned_annotator(job)
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
    return {'dataset_identity': dataset.identity, 'listed_cases': len(rules), 'correction_cases': correction_count, 'verified_masks': len(verified), 'unresolved_cases': len(unresolved), 'correction_package_complete': complete, 'require_full_correction': require_full_correction, 'masks': verified, 'unresolved': unresolved,
            'base_job_identity': job.base_job_identity if isinstance(job, BoundCorrectionJob) else canonical(job),
            'resolved_cases': len(job.resolution_bindings) if isinstance(job, BoundCorrectionJob) else 0}


def load_job_config(path, dataset, require_full_correction=False, allow_unresolved=False):
    """Keep source bytes unchanged; expose separately bound additive permissions."""
    job = read_json(path)
    validate_job(dataset, job, require_full_correction=require_full_correction, allow_unresolved=allow_unresolved)
    return bind_correction_resolutions(dataset, job)


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
    def __init__(self, root, dataset, job=None, reader=None, read_only=False):
        self.root = Path(root).resolve()
        self.dataset = dataset
        self.read_only = bool(read_only)
        need(not within(self.root, dataset.root) and not within(dataset.root, self.root), 'Work folder must be separate from the original dataset.')
        need('dropbox' not in str(self.root).lower() and 'cloudstorage' not in str(self.root).lower() and 'onedrive' not in str(self.root).lower(), 'Choose a local work folder outside live cloud sync folders.')
        self.job = bind_correction_resolutions(dataset, copy.deepcopy(job))
        self.source_job = copy.deepcopy(self.job.source_job if isinstance(self.job, BoundCorrectionJob) else self.job)
        self.job_identity = canonical(self.source_job) if self.source_job else None
        self.base_job_identity = self.job_identity
        self.resolution_bindings = copy.deepcopy(self.job.resolution_bindings if isinstance(self.job, BoundCorrectionJob) else {})
        if self.job is not None:
            validate_job(dataset, self.job, verify_masks=False, allow_unresolved=True)
        protocol = (self.job or {}).get('protocol', {'version': 'draft-practice-1', 'status': 'draft'})
        self.practice_context = validate_practice_context((self.job or {}).get('practice_context'), protocol)
        self.annotator = assigned_annotator(self.job)
        self.reader_assignment = None
        if self.annotator is None:
            need(isinstance(reader, str) and bool(reader.strip()),
                 'Enter your reader name or study ID before starting annotation work.')
            self.annotator = reader.strip()
            self.reader_assignment = {'schema_version': 'meniscus_reader_assignment/1',
                                      'dataset_identity': dataset.identity,
                                      'base_job_identity': self.job_identity,
                                      'reader': self.annotator}
        elif reader is not None:
            need(reader == self.annotator,
                 'The selected reader differs from the explicit job assignment.')
        binding_path = self.root / 'dataset.json'
        binding = {'schema_version': 'meniscus_work/1', 'dataset_identity': dataset.identity, 'dataset_version': dataset.version}
        if self.practice_context is not None:
            binding['practice_context'] = copy.deepcopy(self.practice_context)
        # Claim only a previously empty/unclaimed folder; no overwrite of other datasets or practice scopes.
        if binding_path.exists():
            need(read_json(binding_path) == binding, 'Work folder belongs to a different dataset or practice scope. Reconnect the original configuration or choose a separate local work folder.')
        self.cases_root = self.root / 'cases'
        self.reader_assignment_path = self.root / 'reader_assignment.json'
        self._reader_assignment_persisted = self.reader_assignment_path.exists()
        if self.reader_assignment_path.exists() or self.reader_assignment_path.is_symlink():
            need(self.reader_assignment_path.is_file() and not self.reader_assignment_path.is_symlink()
                 and read_json(self.reader_assignment_path) == self.reader_assignment,
                 'This work folder belongs to a different reader or assignment. Select that reader or choose a separate work folder.')
        elif self.reader_assignment is not None:
            # Claim an existing legacy folder only after checking every saved
            # attribution. Never infer a reader or relabel prior checkpoints.
            known_folders = {self.case_folder(case).name: case for case in dataset.cases}
            if self.cases_root.exists():
                for folder in self.cases_root.iterdir():
                    checkpoints = self._checkpoints(folder)
                    if not checkpoints:
                        continue
                    need(folder.name in known_folders,
                         'Existing work contains an unknown case. Preserve this folder and reconnect its original dataset.')
                    verified_attributions = 0
                    for checkpoint in checkpoints:
                        try:
                            state = read_json(checkpoint / 'annotation.json')
                            manifest = read_json(checkpoint / 'manifest.json')
                            need(isinstance(state, dict) and isinstance(manifest, dict)
                                 and manifest.get('files_sha256', {}).get('annotation.json') == sha256(checkpoint / 'annotation.json')
                                 and manifest.get('source_identity') == known_folders[folder.name].identity,
                                 'Checkpoint attribution is unavailable.')
                        except (ValidationError, OSError, KeyError, TypeError):
                            # Preserve damaged versions and allow the existing
                            # intact-checkpoint recovery path to handle them.
                            continue
                        verified_attributions += 1
                        need(state.get('annotator') == self.annotator
                             and state.get('dataset_identity') == dataset.identity
                             and state.get('job_identity') == self.job_identity,
                             'Existing saved work has a different reader or assignment. Select its recorded reader or choose a separate work folder; saved work was not changed.')
                        saved_binding = state.get('reader_assignment')
                        need(saved_binding is None or saved_binding == self.reader_assignment,
                             'Existing saved work belongs to a different local reader assignment.')
                    need(verified_attributions > 0,
                         'Existing reader attribution cannot be verified. Preserve this work folder and restore a verified checkpoint.')
        if self.read_only:
            need(binding_path.is_file() and self.cases_root.is_dir(),
                 'Select an existing complete work folder for read-only verification.')
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            if not binding_path.exists():
                write_json(binding_path, binding)
            if self.reader_assignment is not None and not self.reader_assignment_path.exists():
                try:
                    write_json(self.reader_assignment_path, self.reader_assignment)
                except FileExistsError:
                    pass  # Another opener must have claimed exactly this reader.
            if self.reader_assignment is not None:
                need(self.reader_assignment_path.is_file() and not self.reader_assignment_path.is_symlink()
                     and read_json(self.reader_assignment_path) == self.reader_assignment,
                     'This work folder was claimed by a different reader or assignment. Choose a separate work folder.')
                self._reader_assignment_persisted = True
            self.cases_root.mkdir(exist_ok=True)

    def case_folder(self, case):
        return self.cases_root / hashlib.sha256(case.key.encode()).hexdigest()[:24]

    def case_resolution(self, case):
        """Recheck the explicit binding before opening, saving or exporting it."""
        if self.reader_assignment is not None and self._reader_assignment_persisted:
            need(self.reader_assignment_path.is_file() and not self.reader_assignment_path.is_symlink()
                 and read_json(self.reader_assignment_path) == self.reader_assignment,
                 'The local reader assignment changed or is unavailable. Reconnect the original work folder; saved work was not changed.')
        binding = self.resolution_bindings.get(case.key)
        if binding is not None:
            need(isinstance(self.job, BoundCorrectionJob) and canonical(self.source_job) == self.job_identity
                 and self.job.base_job_identity == self.job_identity,
                 'Original job identity changed inside the active work configuration.')
            current = bind_correction_resolutions(self.dataset, self.source_job)
            need(isinstance(current, BoundCorrectionJob) and current.resolution_bindings.get(case.key) == binding,
                 'Saved case resolution changed or is unavailable. Reconnect the original explicitly bound correction input.')
            need(self.job.get('cases', {}).get(case.key) == current.get('cases', {}).get(case.key),
                 'Active correction permissions differ from the explicit case resolution.')
        return copy.deepcopy(binding)

    def open_case(self, case):
        need(not self.read_only, 'Read-only verification cannot open an editing session.')
        need(case.key in self.dataset.by_key and self.dataset.by_key[case.key].identity == case.identity, 'Case does not belong to this dataset.')
        self.case_resolution(case)
        require_case_prediction_available(self.job, case.key)
        return CaseSession(self, case)

    def summary(self, case):
        folder = self.case_folder(case)
        checkpoints = self._checkpoints(folder)
        for checkpoint in checkpoints:
            try:
                state = self._validate_checkpoint(checkpoint, case, read_arrays=False)[0]
                expected_job = self.job_identity
                expected_mode = (self.job or {}).get('cases', {}).get(case.key, {}).get('annotation_mode', 'blank')
                if state.get('job_identity') != expected_job or state['initialization']['method'] != expected_mode:
                    return {'status': 'configuration_mismatch', 'previous_status': state['status'],
                            'reviewed': sum(r['reviewed'] for r in state['review']),
                            'flagged': sum(r['flag'] for r in state['review']),
                            'checkpoint': checkpoint.name, 'last_slice': state['last_slice'],
                            'reason': 'Saved work uses a different job configuration. Reconnect the original job and work folder; saved files were not changed.'}
                return {'status': state['status'], 'reviewed': sum(r['reviewed'] for r in state['review']), 'flagged': sum(r['flag'] for r in state['review']), 'checkpoint': checkpoint.name, 'last_slice': state['last_slice']}
            except (ValidationError, OSError, KeyError, ValueError):
                continue
        if checkpoints:
            return {'status': 'saved_unavailable', 'reviewed': 0, 'flagged': 0,
                    'last_slice': 0, 'checkpoint': None,
                    'reason': 'Saved work exists but cannot be validated with this application and job. Preserve the work folder and reconnect the original configuration or restore a verified backup.'}
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
        if 'regional_extension' in manifest:
            from . import regions as regional
            need(manifest['regional_extension'] == {'schema_version': regional.EXTENSION_SCHEMA, 'protocol_status': 'pending_expert_protocol', 'research_approved': False},
                 'Regional extension is unsupported or incorrectly claims research approval.')
            expected |= regional.REGIONAL_FILES
        need(set(manifest.get('files_sha256', {})) == expected, 'Saved checkpoint is incomplete.')
        for name, digest in manifest['files_sha256'].items():
            need(sha256(path / name) == digest, 'Saved checkpoint is corrupt: ' + name)
        state = read_json(path / 'annotation.json')
        self._validate_state(state, case)
        binding = state['initialization'].get('case_resolution')
        if binding is not None:
            need(manifest.get('base_job_identity') == self.job_identity and manifest.get('case_resolution') == binding,
                 'Saved checkpoint case-resolution evidence is missing or mismatched.')
        else:
            need('case_resolution' not in manifest and 'base_job_identity' not in manifest,
                 'Saved checkpoint has unbound correction-resolution evidence.')
        with (path / 'slice_review.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == ['slice_index', 'displayed_slice', 'status', 'attention_flag', 'note'], 'Saved review CSV has unsupported columns.')
            rows = list(reader)
        expected_review = [{'slice_index': str(r['slice_index']), 'displayed_slice': str(r['slice_index']+1), 'status': 'reviewed' if r['reviewed'] else 'not_reviewed', 'attention_flag': str(int(r['flag'])), 'note': r.get('note', '')} for r in state['review']]
        need(rows == expected_review, 'Saved review CSV disagrees with annotation metadata.')
        if not read_arrays:
            if 'regional_extension' in manifest:
                self._read_regions(path, case, state, read_arrays=False)
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
        if 'regional_extension' in manifest:
            self._read_regions(path, case, state, labels, uncertainty)
        return state, labels, uncertainty

    def _read_regions(self, path, case, primary_state, whole=None, whole_uncertainty=None, read_arrays=True):
        """Read the optional extension using the same maintained checkpoint route."""
        from . import regions as regional
        state = read_json(path / 'regions.json')
        regional.validate_state(state, case.n_slices, primary_state)
        with (path / 'regional_review.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == regional.REVIEW_FIELDS, 'Regional review CSV has unsupported columns.')
            need(list(reader) == regional.review_rows(state), 'Regional review CSV disagrees with regional metadata.')
        if not read_arrays:
            return None, None, state
        if whole is None or whole_uncertainty is None:
            whole = np.asarray(check_nifti(path / 'labels.nii.gz', case.shape_xyz, case.affine_ras, True).dataobj).transpose(2, 1, 0).copy()
            whole_uncertainty = np.asarray(check_nifti(path / 'uncertainty.nii.gz', case.shape_xyz, case.affine_ras, True).dataobj).transpose(2, 1, 0).copy()
        arrays = [np.asarray(check_nifti(path / name, case.shape_xyz, case.affine_ras, True).dataobj).transpose(2, 1, 0).copy()
                  for name in ('regions.nii.gz', 'regional_uncertainty.nii.gz', 'regional_validity.nii.gz')]
        regions_array, regional_uncertainty, regional_validity = arrays
        regional.validate(whole, regions_array, regional_uncertainty, state, primary_state)
        expected_validity = regional.validity(whole, whole_uncertainty, regions_array, regional_uncertainty, state, primary_state)
        need(np.array_equal(regional_validity, expected_validity), 'Regional validity disagrees with its pending protocol, uncertainty or review records.')
        return regions_array, regional_uncertainty, state

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
        need(state['annotator'] == self.annotator, 'Saved annotation actor differs from its explicitly selected reader or software-practice role.')
        if self.reader_assignment is not None:
            need(state.get('job_identity') == self.job_identity, 'Saved annotation uses a different original job assignment.')
        saved_reader = state.get('reader_assignment')
        need(saved_reader is None or saved_reader == self.reader_assignment,
             'Saved annotation belongs to a different local reader assignment.')
        if context is not None:
            validate_practice_context(context, state['protocol'])
            need(state['protocol'] == (self.job or {}).get('protocol', {'version': 'draft-practice-1', 'status': 'draft'}), 'Saved software practice protocol differs from the explicit job configuration.')
            need(state.get('annotation_purpose') == 'software_practice' and state.get('status') != 'approved', 'Software practice cannot be an accepted research annotation.')
        reviews = state.get('review', [])
        need(len(reviews) == case.n_slices and all(r.get('slice_index') == k and type(r.get('reviewed')) is bool and type(r.get('flag')) is bool and isinstance(r.get('note'), str) for k, r in enumerate(reviews)), 'Saved slice review records are incomplete.')
        need(type(state.get('last_slice')) is int and 0 <= state['last_slice'] < case.n_slices, 'Saved slice position is invalid.')
        need(state.get('status') in ('in_progress', 'needs_review', 'approved', 'practice_approved'), 'Saved annotation status is invalid.')
        initialization = state['initialization']
        need(initialization.get('case_resolution') == self.case_resolution(case),
             'Saved case resolution differs from the explicit original binding. Preserve the checkpoint and reconnect its original resolution.')
        if initialization['method'] == 'blank':
            need(initialization.get('starting_mask') is None, 'Blank annotation must not contain a starting prediction.')
        else:
            start = initialization.get('starting_mask')
            need(isinstance(start, dict) and all(isinstance(start.get(k), str) and start[k] for k in ('source', 'version', 'sha256')), 'Correction annotation lacks starting-mask provenance.')
            if initialization.get('case_resolution') is not None:
                permission = initialization['case_resolution']['resolution']['starting_mask']
                need(start == {k: permission[k] for k in ('source', 'version', 'sha256')},
                     'Saved correction initialization does not match its separate case-resolution permission.')
        if state['status'] in ('approved', 'practice_approved'):
            approval = state.get('approval')
            need(isinstance(approval, dict) and state.get('approver') == self.annotator and bool(approval.get('approved_utc')), 'Saved approval metadata is incomplete.')
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
        need(not store.read_only, 'Read-only verification cannot open an editing session.')
        store.case_resolution(case)
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
            self._regional_loaded = None
            self.regional_state = None
            self._primary_saved_state = None
            candidates = store._checkpoints(self.folder)
            for candidate in candidates:
                try:
                    state, labels, uncertainty = store._validate_checkpoint(candidate, case)
                except (ValidationError, OSError, KeyError, ValueError):
                    continue
                need(state.get('job_identity') == self.state.get('job_identity') and state['initialization']['method'] == self.state['initialization']['method'], 'Saved initialization permissions differ from the current job configuration. Reopen with the original explicit job or use a separate work folder.')
                self.state = state
                self._primary_saved_state = copy.deepcopy(state)
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
        state = {'schema_version': 'meniscus_annotation/1', 'app_version': APP_VERSION,
                'dataset_identity': self.store.dataset.identity, 'source_identity': self.case.identity,
                'source_image_sha256': self.case.metadata['image_sha256'], 'case_key': self.case.key,
                'source': copy.deepcopy(self.case.metadata), 'label_mapping': {'0': 'background', '1': 'medial meniscus', '2': 'lateral meniscus'},
                'array_convention': 'files IJK; application arrays KJI; displayed slice n = stored k + 1',
                'review': [{'slice_index': k, 'reviewed': False, 'flag': False, 'note': ''} for k in range(self.case.n_slices)],
                'notes': '', 'compartments': {'medial': False, 'lateral': False}, 'protocol': copy.deepcopy(protocol),
                'practice_context': copy.deepcopy(self.store.practice_context),
                'annotation_purpose': 'software_practice' if self.store.practice_context is not None else 'research_annotation',
                'annotator': self.store.annotator, 'approver': None, 'approval': None,
                'initialization': {'method': mode, 'starting_mask': None}, 'job_identity': self.store.job_identity,
                'last_slice': 0, 'status': 'in_progress', 'created_utc': now(), 'saved_utc': None,
                'uncertainty_policy': 'Separate binary overlay may overlap anatomical labels; all uncertainty and attention flags must be resolved before approval. ' + ('SOFTWARE PRACTICE validity is zero for every voxel; review flags do not confirm anatomical labels or background.' if self.store.practice_context is not None else 'Training validity excludes uncertain and unreviewed/flagged voxels.'),
                'technical_acceptance_scope': 'Identity, byte integrity, native geometry, label mapping and review completeness only; not anatomical correctness. Downstream training-loader integration is a separate requirement.'}
        binding = self.store.case_resolution(self.case)
        if binding is not None:
            state['initialization']['case_resolution'] = binding
        if self.store.reader_assignment is not None:
            state['reader_assignment'] = copy.deepcopy(self.store.reader_assignment)
        return state

    def blank_arrays(self):
        return (np.zeros(self.case.shape_xyz[::-1], dtype=np.uint8), np.zeros(self.case.shape_xyz[::-1], dtype=np.uint8))

    def load(self):
        self.store.case_resolution(self.case)
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

    def load_regions(self):
        """Return separate regional draft arrays/state without changing legacy work."""
        need(not self.closed, 'This case session is closed.')
        self.store.case_resolution(self.case)
        from . import regions as regional
        if self._regional_loaded is None:
            whole, whole_uncertainty, _ = self.load()
            manifest = read_json(self.current_checkpoint / 'manifest.json') if self.current_checkpoint else {}
            if 'regional_extension' in manifest:
                self.store._validate_checkpoint(self.current_checkpoint, self.case)
                region_array, uncertain, state = self.store._read_regions(self.current_checkpoint, self.case, self.state, whole, whole_uncertainty)
            else:
                region_array = regional.initialize(whole)
                uncertain = np.zeros_like(whole, dtype=np.uint8)
                state = regional.default_state(self.case.n_slices, self.state)
            self._regional_loaded = (region_array.copy(), uncertain.copy())
            self.regional_state = copy.deepcopy(state)
        return self._regional_loaded[0].copy(), self._regional_loaded[1].copy(), copy.deepcopy(self.regional_state)

    def _regional_primary_approval_unchanged(self, labels, uncertainty):
        """A regional-only draft must not manufacture or erase whole approval."""
        if self._primary_saved_state is None or self._loaded is None:
            return False
        if self._primary_saved_state.get('status') not in ('approved', 'practice_approved'):
            return False
        if not np.array_equal(labels, self._loaded[0]) or not np.array_equal(uncertainty, self._loaded[1]):
            return False
        incidental = {'last_slice', 'runtime', 'saved_utc'}
        before = {key: value for key, value in self._primary_saved_state.items() if key not in incidental}
        current = {key: value for key, value in self.state.items() if key not in incidental}
        return before == current

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

    def save(self, labels, uncertainty, seg_writer, approve=False, practice=False,
             regions=None, regional_uncertainty=None, regional_state=None):
        need(not self.closed, 'This case session is closed.')
        self.store.case_resolution(self.case)
        self.case.verify_source()
        if self.state['initialization']['method'] == 'correction' and self.state['initialization']['starting_mask'] is None:
            self.load()
        array_check(labels, uncertainty, self.case)
        from . import regions as regional
        regional_args = (regions, regional_uncertainty, regional_state)
        explicit_regional = any(value is not None for value in regional_args)
        need(not explicit_regional or all(value is not None for value in regional_args), 'Save all three regional arrays/metadata together; partial regional payloads are not permitted.')
        inherited_regional = False
        if not explicit_regional and self.current_checkpoint is not None:
            inherited_regional = 'regional_extension' in read_json(self.current_checkpoint / 'manifest.json')
            if inherited_regional:
                regions, regional_uncertainty, regional_state = self.load_regions()
                regions, regional_uncertainty, regional_state = regional.reconcile(labels, regions, regional_uncertainty, regional_state,
                                                                                   previous_whole=self._loaded[0])
                # A legacy caller must not retain regional review after changing
                # whole uncertainty while carrying an existing extension forward.
                changed_uncertainty = uncertainty != self._loaded[1]
                for parent, value in regional.PARENT_VALUES.items():
                    affected = changed_uncertainty & ((labels == value) | (self._loaded[0] == value))
                    indices = [int(k) for k in np.flatnonzero(np.any(affected, axis=(1, 2)))]
                    regional_state = regional.invalidate_review(regional_state, indices, (parent,))
        has_regional = explicit_regional or inherited_regional
        if has_regional:
            regional.validate(labels, regions, regional_uncertainty, regional_state, self.state)
            regional_state = copy.deepcopy(regional_state)
            regional_state['saved_utc'] = now()
            regional_state['runtime'] = copy.deepcopy(self.state.get('runtime'))
        preserve_primary_approval = has_regional and self._regional_primary_approval_unchanged(labels, uncertainty)
        if approve:
            errors = self.approval_errors(labels, uncertainty, practice)
            need(not errors, ' '.join(errors))
        # Editing previously approved content always creates a new draft checkpoint.
        state = copy.deepcopy(self.state)
        if self.store.reader_assignment is not None:
            state['reader_assignment'] = copy.deepcopy(self.store.reader_assignment)
        if not approve and not preserve_primary_approval and state['status'] in ('approved', 'practice_approved'):
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
                state.update(status='practice_approved' if practice else 'approved', approver=self.store.annotator,
                             approval={'approved_utc': now(), 'role': 'assigned annotator and approver; not an independent second reader', 'practice_only': bool(practice), 'deliberate_approval_required_by_ui': True})
        elif not preserve_primary_approval and state['status'] not in ('in_progress', 'needs_review'):
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
            need(shutil.disk_usage(versions).free >= max(16 * 1024 * 1024, labels.nbytes * (9 if has_regional else 5)), 'Insufficient free disk space. Free space or choose another local work folder.')
            pending.mkdir()
            write_native(pending / 'labels.nii.gz', labels, self.case)
            write_native(pending / 'uncertainty.nii.gz', uncertainty, self.case)
            write_native(pending / 'validity.nii.gz', validity_array(state, uncertainty), self.case)
            if has_regional:
                write_native(pending / 'regions.nii.gz', regions, self.case)
                write_native(pending / 'regional_uncertainty.nii.gz', regional_uncertainty, self.case)
                write_native(pending / 'regional_validity.nii.gz', regional.validity(labels, uncertainty, regions, regional_uncertainty, regional_state, state), self.case)
                write_json(pending / 'regions.json', regional_state)
                with (pending / 'regional_review.csv').open('x', encoding='utf-8', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=regional.REVIEW_FIELDS)
                    writer.writeheader()
                    writer.writerows(regional.review_rows(regional_state))
                    stream.flush()
                    os.fsync(stream.fileno())
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
            if has_regional:
                names += sorted(regional.REGIONAL_FILES)
            manifest = {'schema_version': 'meniscus_checkpoint/1', 'checkpoint': checkpoint_id, 'source_identity': self.case.identity,
                        'source_image_sha256': self.case.metadata['image_sha256'], 'files_sha256': {n: sha256(pending / n) for n in names},
                        'technical_checks': 'All NIfTI outputs reopened with nibabel and compared voxel-for-voxel to in-memory KJI arrays; full grid and qform/sform checked.'}
            if has_regional:
                manifest['regional_extension'] = {'schema_version': regional.EXTENSION_SCHEMA, 'protocol_status': 'pending_expert_protocol', 'research_approved': False}
            if 'case_resolution' in state['initialization']:
                manifest['base_job_identity'] = self.store.job_identity
                manifest['case_resolution'] = copy.deepcopy(state['initialization']['case_resolution'])
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
            self._primary_saved_state = copy.deepcopy(state)
            self.current_checkpoint = final
            self._loaded = (labels.copy(), uncertainty.copy(), final / 'segmentation.seg.nrrd')
            if has_regional:
                self._regional_loaded = (regions.copy(), regional_uncertainty.copy())
                self.regional_state = copy.deepcopy(regional_state)
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
        store.case_resolution(case)
        case.verify_source()
        # Export most recent preserved approved version, even if a later draft exists.
        found = None
        for checkpoint in store._checkpoints(store.case_folder(case)):
            try:
                state, labels, uncertainty = store._validate_checkpoint(checkpoint, case)
                allowed = ('approved', 'practice_approved') if include_practice else ('approved',)
                if state['status'] not in allowed:
                    continue
                expected_job = store.job_identity
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
                receipt = {'case_key': case.key, 'folder': 'cases/' + export_key, 'checkpoint': checkpoint.name,
                                 'source_identity': case.identity, 'source_image_sha256': case.metadata['image_sha256'],
                                 'manifest_sha256': sha256(checkpoint / 'manifest.json'), 'status': state['status']}
                checkpoint_metadata = read_json(checkpoint / 'manifest.json')
                if 'regional_extension' in checkpoint_metadata:
                    receipt['regional_extension'] = copy.deepcopy(checkpoint_metadata['regional_extension'])
                    receipt['regional_annotation_status'] = 'draft; pending expert anatomical protocol; not research approved'
                if 'case_resolution' in state['initialization']:
                    receipt['base_job_identity'] = store.job_identity
                    receipt['case_resolution'] = copy.deepcopy(state['initialization']['case_resolution'])
                receipts.append(receipt)
            manifest = {'schema_version': 'meniscus_results/1', 'created_utc': now(), 'app_version': APP_VERSION,
                        'dataset_identity': store.dataset.identity, 'dataset_version': store.dataset.version,
                        'practice_only': practice, 'software_practice': software_practice, 'cases': receipts,
                        'training_contract': 'labels 0/1/2 fixed background/medial/lateral; use validity.nii.gz to interpret background. Uncertainty is separate, never a third training class.',
                        'limits': 'Technical acceptance is not anatomical validation. Actor roles are recorded per case. Actual downstream training-loader integration must be checked separately.'}
            if any('regional_extension' in receipt for receipt in receipts):
                manifest['regional_annotation_contract'] = 'Optional regional files are drafts only. Values 1/2/3 medial anterior/body/posterior; 4/5/6 lateral anterior/body/posterior; 7 medial unassigned; 8 lateral unassigned; 0 outside whole menisci. Regional validity is zero everywhere while expert protocol is pending. Whole approval is independent and never implies regional approval.'
            if software_practice:
                manifest.update(practice_context=copy.deepcopy(store.practice_context), accepted_research_annotation=False, human_anatomical_approval=False)
                manifest['training_contract'] += ' SOFTWARE PRACTICE: validity is zero across the entire grid; no voxel is confirmed training anatomy or background.'
            archive.writestr('results.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', ('SOFTWARE PRACTICE — NOT ACCEPTED RESEARCH ANNOTATIONS; NOT HUMAN ANATOMICAL APPROVAL\nEvery validity voxel is zero. Review flags exercise software only; labels/background are not anatomically confirmed.\n' if software_practice else ('PRACTICE ONLY — NOT RESEARCH APPROVAL\n' if practice else '')) + 'Versioned approved annotations on the original full acquired grid. MRI images are omitted.\nlabels.nii.gz: 0 background, 1 medial, 2 lateral. uncertainty.nii.gz: binary uncertainty.\nOnly voxels with validity.nii.gz = 1 may be treated as reviewed known labels/background.\nTechnical validation does not establish anatomical correctness.\nOptional regional files remain DRAFT / PENDING EXPERT PROTOCOL, never research approved. regions.nii.gz uses 1 medial anterior, 2 medial body, 3 medial posterior, 4 lateral anterior, 5 lateral body, 6 lateral posterior, 7 medial unassigned, 8 lateral unassigned, 0 outside whole menisci. Regional validity is zero everywhere; do not use these draft regional assignments as accepted training targets. Whole approval does not approve regions.\n')
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
