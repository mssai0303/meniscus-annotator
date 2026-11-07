"""Synthetic additive permissions preserve the historical global job binding."""
import copy
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pytest

from test_correction_jobs import correction
from MeniscusAnnotatorLib import core
from MeniscusAnnotatorLib.correction_resolutions import FILENAME, LABEL_MAPPING


def put(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


@pytest.fixture
def resolved(correction):
    dataset, job, arrays = correction
    case = dataset.cases[0]
    start = copy.deepcopy(job['cases'][case.key]['starting_mask'])
    start['source'] = 'SYNTHETIC documented case-specific assignment'
    start['version'] = 'SYNTHETIC-RESOLUTION-1'
    job['cases'][case.key] = {'annotation_mode': 'correction', 'availability': 'unresolved',
                              'reason': 'SYNTHETIC original output is binary', 'starting_mask': None}
    sidecar = {'schema_version': 'meniscus_starting_mask/1',
               **{k: case.metadata[k] for k in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')},
               'status': 'unreviewed_automated_prediction', 'prepared_mask_sha256': start['sha256'],
               'label_mapping': LABEL_MAPPING,
               'source_prediction': {'sha256': 'b' * 64, 'pipeline_version': 'SYNTHETIC-PIPELINE-1', 'model_version': 'SYNTHETIC-MODEL-1'},
               'transformation': {'method': 'SYNTHETIC documented assignment on original grid'},
               'verification': {'status': 'verified', 'native_grid_match': True,
                                'independent_target_voxel_mapping_match': True, 'output_labels_valid': True}}
    sidecar_path = case.folder / 'starting_mask.json';put(sidecar_path, sidecar)
    entry = {'source_identity': case.identity, 'source_series_key': case.metadata['source_series_key'],
             'series_instance_uid': case.metadata['series_instance_uid'], 'source_image_sha256': case.metadata['image_sha256'],
             'original_rule_identity': core.canonical(job['cases'][case.key]), 'starting_mask': start,
             'provenance': {'path': sidecar_path.relative_to(dataset.root).as_posix(), 'sha256': core.sha256(sidecar_path)}}
    registry = {'schema_version': 'meniscus_correction_resolutions/1', 'base_job_identity': core.canonical(job),
                'dataset_identity': dataset.identity, 'resolutions': {case.key: entry}}
    put(dataset.root / 'correction_job.json', job)
    put(dataset.root / FILENAME, registry)
    return dataset, job, arrays, registry, case


def save(session, approve=False):
    labels, uncertainty, _ = session.load()
    if approve:
        for row in session.state['review']:
            row['reviewed'] = True
        session.state['compartments'] = {'medial': True, 'lateral': True}
    return session.save(labels, uncertainty, lambda path: path.write_bytes(b'SYNTHETIC editable marker'), approve=approve, practice=approve)


def test_resolution_loads_without_mutating_base_global_identity_or_old_checkpoint(resolved, tmp_path):
    dataset, job, arrays, registry, case = resolved
    raw_bytes = (dataset.root / 'correction_job.json').read_bytes()
    base_identity = core.canonical(job)
    registry_bytes = (dataset.root / FILENAME).read_bytes();(dataset.root / FILENAME).unlink()
    old_store = core.WorkStore(tmp_path / 'Existing work', dataset, job)
    ready = dataset.cases[1]
    with old_store.open_case(ready) as session:
        checkpoint = save(session)
        old_state = copy.deepcopy(session.state)
    before = {p.name: p.read_bytes() for p in checkpoint.iterdir() if p.is_file()}
    (dataset.root / FILENAME).write_bytes(registry_bytes)
    loaded, _ = core.load_dataset_job_config(dataset)
    assert isinstance(loaded, core.BoundCorrectionJob)
    assert loaded['cases'][case.key]['availability'] == 'ready'
    assert loaded.source_job == job and loaded.base_job_identity == base_identity
    assert core.canonical(loaded) != base_identity  # canonical() was not overridden.
    store = core.WorkStore(old_store.root, dataset, loaded)
    assert store.source_job == job and store.job_identity == base_identity
    assert store.summary(ready)['status'] == 'in_progress'
    with store.open_case(ready) as reopened:
        assert reopened.state == old_state and 'case_resolution' not in reopened.state['initialization']
    assert before == {p.name: p.read_bytes() for p in checkpoint.iterdir() if p.is_file()}
    with store.open_case(case) as session:
        assert (session.load()[0] == arrays[case.key]).all()
        assert session.state['job_identity'] == base_identity
        assert session.state['initialization']['case_resolution']['base_job_identity'] == base_identity
        assert not any(r['reviewed'] for r in session.state['review'])
        save(session)
    with core.WorkStore(store.root, dataset, job).open_case(case) as reopened:
        assert reopened.state['job_identity'] == base_identity
        assert reopened.state['initialization']['case_resolution'] == store.resolution_bindings[case.key]
    report = core.validate_job(dataset, job, require_full_correction=True)
    assert report['correction_package_complete'] and report['verified_masks'] == 2
    assert report['resolved_cases'] == 1 and report['base_job_identity'] == base_identity
    assert job['cases'][case.key]['availability'] == 'unresolved'
    assert (dataset.root / 'correction_job.json').read_bytes() == raw_bytes


def test_local_reader_assignment_survives_additive_resolution(resolved, tmp_path):
    dataset, job, _, registry, case = resolved
    job.pop('practice_context')
    registry['base_job_identity'] = core.canonical(job)
    put(dataset.root / 'correction_job.json', job)
    (dataset.root / FILENAME).unlink()
    store = core.WorkStore(tmp_path / 'Local reader work', dataset, job, reader='Synthetic Reader A')
    reader_binding = store.reader_assignment_path.read_bytes()
    with store.open_case(dataset.cases[1]) as session:
        checkpoint = save(session)
    checkpoint_bytes = {p.name: p.read_bytes() for p in checkpoint.iterdir() if p.is_file()}
    put(dataset.root / FILENAME, registry)
    loaded, _ = core.load_dataset_job_config(dataset)
    resumed = core.WorkStore(store.root, dataset, loaded, reader='Synthetic Reader A')
    assert resumed.job_identity == core.canonical(job)
    assert resumed.reader_assignment_path.read_bytes() == reader_binding
    with resumed.open_case(case) as session:
        save(session)
        assert session.state['annotator'] == 'Synthetic Reader A'
        assert session.state['initialization']['case_resolution'] == resumed.resolution_bindings[case.key]
    with resumed.open_case(dataset.cases[1]) as session:
        assert session.current_checkpoint == checkpoint
    assert checkpoint_bytes == {p.name: p.read_bytes() for p in checkpoint.iterdir() if p.is_file()}


@pytest.mark.parametrize('field', ['base_job_identity', 'dataset_identity', 'case_key', 'source_identity',
                                  'source_series_key', 'series_instance_uid', 'source_image_sha256',
                                  'original_rule_identity', 'mask_sha256', 'provenance_sha256',
                                  'absolute_path', 'traversal', 'wrong_case_path', 'sidecar_path'])
def test_resolution_wrong_identity_hash_or_path_is_rejected(resolved, field):
    dataset, job, _, registry, case = resolved
    entry = registry['resolutions'][case.key]
    if field in ('base_job_identity', 'dataset_identity'):
        registry[field] = '0' * 64
    elif field == 'case_key':
        registry['resolutions']['SYNTHETIC_UNKNOWN'] = registry['resolutions'].pop(case.key)
    elif field in ('source_identity', 'source_series_key', 'series_instance_uid', 'source_image_sha256', 'original_rule_identity'):
        entry[field] = 'SYNTHETIC_WRONG'
    elif field == 'mask_sha256':
        entry['starting_mask']['sha256'] = '0' * 64
    elif field == 'provenance_sha256':
        entry['provenance']['sha256'] = '0' * 64
    elif field == 'sidecar_path':
        entry['provenance']['path'] = dataset.cases[1].folder.relative_to(dataset.root).as_posix() + '/starting_mask.json'
    else:
        entry['starting_mask']['path'] = {'absolute_path': str(case.folder / 'starting_mask.nii.gz'),
                                         'traversal': '../outside.nii.gz',
                                         'wrong_case_path': dataset.cases[1].folder.relative_to(dataset.root).as_posix() + '/starting_mask.nii.gz'}[field]
    put(dataset.root / FILENAME, registry)
    with pytest.raises(core.ValidationError):
        core.validate_job(dataset, job, require_full_correction=True)


def test_ready_case_cannot_be_overridden_even_with_its_rule_hash(resolved):
    dataset, job, _, registry, case = resolved
    ready = dataset.cases[1]
    entry = copy.deepcopy(registry['resolutions'][case.key])
    entry['original_rule_identity'] = core.canonical(job['cases'][ready.key])
    registry['resolutions'][ready.key] = entry
    put(dataset.root / FILENAME, registry)
    with pytest.raises(core.ValidationError, match='ready cases cannot be overridden'):
        core.validate_job(dataset, job)


@pytest.mark.parametrize('kind', ['invalid_label', 'wrong_grid'])
def test_resolved_mask_still_passes_existing_native_image_checks(resolved, kind):
    dataset, job, _, registry, case = resolved
    mask = case.folder / 'starting_mask.nii.gz'
    labels = np.zeros(case.shape_xyz[::-1], dtype=np.uint8)
    labels[0, 1, 2] = 3 if kind == 'invalid_label' else 1
    if kind == 'wrong_grid':
        import nibabel as nib
        affine = case.affine_ras.copy();affine[0, 3] += 10
        image = nib.Nifti1Image(labels.transpose(2, 1, 0), affine)
        image.header.set_xyzt_units('mm');image.set_qform(affine, code=1);image.set_sform(affine, code=1)
        nib.save(image, str(mask))
    else:
        core.write_native(mask, labels, case)
    entry = registry['resolutions'][case.key];entry['starting_mask']['sha256'] = core.sha256(mask)
    sidecar = case.folder / 'starting_mask.json';metadata = json.loads(sidecar.read_text())
    metadata['prepared_mask_sha256'] = core.sha256(mask);put(sidecar, metadata)
    entry['provenance']['sha256'] = core.sha256(sidecar);put(dataset.root / FILENAME, registry)
    with pytest.raises(core.ValidationError, match='labels|source geometry'):
        core.validate_job(dataset, job, require_full_correction=True)


def test_changed_resolution_blocks_active_load_save_reopen_and_export(resolved, tmp_path):
    dataset, job, _, registry, case = resolved
    store = core.WorkStore(tmp_path / 'Case work', dataset, job)
    with store.open_case(case) as session:
        checkpoint = save(session, approve=True)
        labels, uncertainty, _ = session.load()
        registry['resolutions'][case.key]['starting_mask']['version'] = 'SYNTHETIC-CHANGED-RESOLUTION-2'
        put(dataset.root / FILENAME, registry)
        with pytest.raises(core.ValidationError, match='resolution changed'):
            session.load()
        with pytest.raises(core.ValidationError, match='resolution changed'):
            session.save(labels, uncertainty, lambda path: path.write_bytes(b'SYNTHETIC marker'))
    with pytest.raises(core.ValidationError, match='resolution changed'):
        store.open_case(case)
    with pytest.raises(core.ValidationError, match='resolution changed'):
        core.export_approved(store, tmp_path / 'Blocked exports', [case.key], include_practice=True)
    changed_store = core.WorkStore(store.root, dataset, job)
    assert changed_store.job_identity == store.job_identity == core.canonical(job)
    with pytest.raises(core.ValidationError, match='No intact saved version'):
        changed_store.open_case(case)
    with pytest.raises(core.ValidationError, match='case resolution differs'):
        core.export_approved(changed_store, tmp_path / 'Blocked exports', [case.key], include_practice=True)
    assert checkpoint.exists()


def test_export_records_separate_resolution_and_original_global_job(resolved, tmp_path):
    dataset, job, _, _, case = resolved
    store = core.WorkStore(tmp_path / 'Resolved work', dataset, job)
    with store.open_case(case) as session:
        save(session, approve=True)
    output = core.export_approved(store, tmp_path / 'Synthetic exports', [case.key], include_practice=True)
    with zipfile.ZipFile(output) as archive:
        results = json.loads(archive.read('results.json'))
        receipt = results['cases'][0]
        assert receipt['base_job_identity'] == core.canonical(job)
        assert receipt['case_resolution'] == store.resolution_bindings[case.key]
        annotation = json.loads(archive.read(receipt['folder'] + '/annotation.json'))
        manifest = json.loads(archive.read(receipt['folder'] + '/manifest.json'))
        assert annotation['job_identity'] == manifest['base_job_identity'] == core.canonical(job)
        assert annotation['initialization']['case_resolution'] == manifest['case_resolution']
        assert results['software_practice'] is True


def test_registry_and_sidecar_symlinks_rejected(resolved, tmp_path):
    dataset, job, _, registry, case = resolved
    original = dataset.root / FILENAME;target = tmp_path / 'registry.json';shutil.copyfile(original, target)
    original.unlink();original.symlink_to(target)
    with pytest.raises(core.ValidationError, match='regular local file'):
        core.validate_job(dataset, job)
    original.unlink();put(original, registry)
    sidecar = case.folder / 'starting_mask.json';target = tmp_path / 'sidecar.json';shutil.copyfile(sidecar, target)
    sidecar.unlink();sidecar.symlink_to(target)
    with pytest.raises(core.ValidationError, match='symbolic link|leaves the dataset'):
        core.validate_job(dataset, job)


def test_preparation_contract_copy_is_identical():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'MeniscusAnnotatorLib/correction_resolutions.py').read_bytes() == (root / 'tools/preparation/correction_resolutions.py').read_bytes()
