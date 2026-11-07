"""Synthetic correction permissions, portability and fail-closed availability."""
import copy
import json
from pathlib import Path
import shutil
import sys

import nibabel as nib
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import core
from tools.make_synthetic import make_synthetic


@pytest.fixture
def correction(tmp_path):
    dataset = core.Dataset(make_synthetic(tmp_path / 'Synthetic sources', layout='flat'))
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': dataset.identity,
           'protocol': {'version': 'SYNTHETIC-CORRECTION-PRACTICE-1', 'status': 'draft'},
           'practice_context': {'purpose': 'software_practice', 'actor_type': 'automated', 'actor': 'Software QA (automated)'},
           'cases': {}}
    arrays = {}
    for case in dataset.cases:
        values = np.zeros(case.shape_xyz[::-1], dtype=np.uint8)
        values[4, 12:14, 15:17] = 1
        values[6, 18:20, 25:27] = 2
        path = case.folder / 'starting_mask.nii.gz'
        core.write_native(path, values, case)
        job['cases'][case.key] = {'annotation_mode': 'correction', 'starting_mask': {'path': path.relative_to(dataset.root).as_posix(), 'sha256': core.sha256(path), 'source': 'SYNTHETIC PHANTOM; NOT A MODEL PREDICTION', 'version': 'SYNTHETIC-1'}}
        arrays[case.key] = values
    return dataset, job, arrays


def test_read_only_full_validation_is_cwd_independent_and_does_not_mutate_job(correction, tmp_path, monkeypatch):
    dataset, job, _ = correction
    before = copy.deepcopy(job)
    hashes = {str(p): core.sha256(p) for p in dataset.root.rglob('*') if p.is_file()}
    elsewhere = tmp_path / 'Unrelated CWD'; elsewhere.mkdir(); monkeypatch.chdir(elsewhere)
    report = core.validate_job(dataset, job, require_full_correction=True)
    assert report['verified_masks'] == report['listed_cases'] == 2
    assert report['correction_package_complete'] is True and job == before
    assert hashes == {str(p): core.sha256(p) for p in dataset.root.rglob('*') if p.is_file()}
    assert not (elsewhere / 'cases').exists()


def test_relative_correction_save_reopen_after_complete_package_move(correction, tmp_path):
    dataset, job, arrays = correction
    case = dataset.cases[1]
    work = tmp_path / 'Separate correction work'
    store = core.WorkStore(work, dataset, job)
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        assert np.array_equal(labels, arrays[case.key])
        labels[5, 20, 30] = 2
        session.mark_changed([5])
        session.state['last_slice'] = 5
        session.save(labels, uncertainty, lambda p: p.write_bytes(b'SYNTHETIC PERSISTENCE MARKER'), approve=False)
        assert session.state['annotator'] == 'Software QA (automated)'
        assert session.state['approver'] is None
    moved_root = tmp_path / 'Relocated package'
    shutil.copytree(dataset.root, moved_root)
    moved = core.Dataset(moved_root)
    assert moved.identity == dataset.identity
    same_job = copy.deepcopy(job)
    with core.WorkStore(work, moved, same_job).open_case(moved.by_key[case.key]) as reopened:
        actual, _, _ = reopened.load()
        assert np.array_equal(actual, labels) and reopened.state['last_slice'] == 5
        assert reopened.state['job_identity'] == core.canonical(job)
        assert not reopened.state['approval'] and not np.asarray(nib.load(reopened.current_checkpoint / 'validity.nii.gz').dataobj).any()


def test_legacy_absolute_starting_mask_path_still_supported(correction):
    dataset, job, _ = correction
    case = dataset.cases[0]
    job['cases'][case.key]['starting_mask']['path'] = str(case.folder / 'starting_mask.nii.gz')
    assert core.validate_job(dataset, job, require_full_correction=True)['verified_masks'] == 2


@pytest.mark.parametrize('bad', ['../outside.nii.gz', 'Cases\\outside.nii.gz'])
def test_unsafe_relative_starting_mask_paths_rejected(correction, bad):
    dataset, job, _ = correction
    job['cases'][dataset.cases[0].key]['starting_mask']['path'] = bad
    with pytest.raises(core.ValidationError, match='unsafe'):
        core.validate_job(dataset, job, require_full_correction=True)


def test_relative_mask_symlink_rejected_even_if_inside_package(correction):
    dataset, job, _ = correction
    case = dataset.cases[0]; path = case.folder / 'starting_mask.nii.gz'
    copied = case.folder / 'other.nii.gz'; shutil.copy2(path, copied); path.unlink(); path.symlink_to(copied)
    with pytest.raises(core.ValidationError, match='symbolic link'):
        core.validate_job(dataset, job)


def test_full_correction_job_cannot_default_omitted_case_to_blank(correction):
    dataset, job, _ = correction
    del job['cases'][dataset.cases[0].key]
    with pytest.raises(core.ValidationError, match='every case'):
        core.validate_job(dataset, job, require_full_correction=True)


def test_full_correction_job_cannot_explicitly_choose_blank(correction):
    dataset, job, _ = correction
    job['cases'][dataset.cases[0].key] = {'annotation_mode': 'blank'}
    with pytest.raises(core.ValidationError, match='correction for every case'):
        core.validate_job(dataset, job, require_full_correction=True)


def test_full_correction_job_does_not_invent_protocol_metadata(correction):
    dataset, job, _ = correction
    del job['protocol'];job.pop('practice_context')
    with pytest.raises(core.ValidationError, match='explicit documented protocol'):
        core.validate_job(dataset, job, require_full_correction=True)


def test_unresolved_case_is_explicit_incomplete_and_blocked_before_work_creation(correction, tmp_path):
    dataset, job, _ = correction
    blocked = dataset.cases[0]
    job['cases'][blocked.key] = {'annotation_mode': 'correction', 'availability': 'unresolved', 'reason': 'SYNTHETIC source has no established compartment assignment', 'starting_mask': None}
    before = copy.deepcopy(job)
    with pytest.raises(core.ValidationError, match='incomplete'):
        core.validate_job(dataset, job, require_full_correction=True)
    report = core.validate_job(dataset, job, require_full_correction=True, allow_unresolved=True)
    assert report['verified_masks'] == report['unresolved_cases'] == 1
    assert not report['correction_package_complete'] and job == before
    store = core.WorkStore(tmp_path / 'Correction work', dataset, job)
    path = store.case_folder(blocked)
    assert not path.exists()
    with pytest.raises(core.ValidationError, match='blocked; no blank'):
        store.open_case(blocked)
    with pytest.raises(core.ValidationError, match='blocked; no blank'):
        core.CaseSession(store, blocked)
    assert not path.exists()
    with store.open_case(dataset.cases[1]) as available:
        assert available.load()[0].any()


@pytest.mark.parametrize('bad', [None, '', 5])
def test_unresolved_case_requires_actionable_reason(correction, bad):
    dataset, job, _ = correction
    job['cases'][dataset.cases[0].key] = {'annotation_mode': 'correction', 'availability': 'unresolved', 'reason': bad, 'starting_mask': None}
    with pytest.raises(core.ValidationError, match='explicit reason'):
        core.validate_job(dataset, job, allow_unresolved=True)


def test_job_file_remains_byte_identical_after_load(correction):
    dataset, job, _ = correction
    file = dataset.root / 'correction_job.json'; file.write_text(json.dumps(job, indent=2))
    before = file.read_bytes()
    assert core.load_job_config(file, dataset, require_full_correction=True) == job
    assert file.read_bytes() == before


def test_default_package_job_loads_explicit_correction_without_changes(correction):
    dataset, job, _ = correction
    path = dataset.root / 'correction_job.json';path.write_text(json.dumps(job))
    loaded, chosen = core.load_dataset_job_config(dataset)
    assert loaded == job and chosen == str(path)


def test_known_starting_masks_without_job_never_default_to_blank(correction):
    dataset, _, _ = correction
    with pytest.raises(core.ValidationError, match='cannot default to blank'):
        core.load_dataset_job_config(dataset)


def test_legacy_mri_only_package_without_job_keeps_legacy_mode(tmp_path):
    dataset = core.Dataset(make_synthetic(tmp_path / 'Legacy MRI-only source', layout='legacy'))
    assert core.load_dataset_job_config(dataset) == (None, None)


@pytest.mark.parametrize('packaged_job', [False, True])
def test_remembered_blank_job_cannot_override_correction_package(correction, tmp_path, packaged_job):
    dataset, job, _ = correction
    if packaged_job:(dataset.root / 'correction_job.json').write_text(json.dumps(job))
    old = copy.deepcopy(job)
    old['cases'] = {case.key: {'annotation_mode': 'blank'} for case in dataset.cases}
    path = tmp_path / 'old-blank-job.json';path.write_text(json.dumps(old))
    with pytest.raises(core.ValidationError, match='correction for every case'):
        core.load_dataset_job_config(dataset, remembered_path=path)


def test_fixed_software_practice_job_stays_explicit_and_immutable(correction, tmp_path):
    dataset, job, _ = correction
    (dataset.root / 'correction_job.json').write_text(json.dumps(job))
    fixed = copy.deepcopy(job)
    fixed['cases'] = {case.key: {'annotation_mode': 'blank'} for case in dataset.cases}
    path = tmp_path / 'fixed-software-practice.json';path.write_text(json.dumps(fixed))
    loaded, chosen = core.load_dataset_job_config(dataset, remembered_path='ignore-remembered.json', fixed_job_path=path)
    assert loaded == fixed and chosen == str(path)


def test_package_job_symlink_rejected_instead_of_blank(correction):
    dataset, _, _ = correction
    (dataset.root / 'correction_job.json').symlink_to(dataset.root / 'missing-job.json')
    with pytest.raises(core.ValidationError, match='symbolic link'):
        core.load_dataset_job_config(dataset)


def test_missing_ready_mask_is_blocked_without_blank_fallback(correction):
    dataset, job, _ = correction
    (dataset.cases[0].folder / 'starting_mask.nii.gz').unlink()
    with pytest.raises(core.ValidationError, match='unavailable.*cannot become blank'):
        core.validate_job(dataset, job, require_full_correction=True)


@pytest.mark.parametrize('kind', ['checksum', 'label_value', 'geometry', 'float_storage'])
def test_invalid_starting_masks_fail_existing_native_input_checks(correction, kind):
    dataset, job, arrays = correction
    case = dataset.cases[0]; rule = job['cases'][case.key]['starting_mask']; path = case.folder / 'starting_mask.nii.gz'
    if kind == 'checksum':
        rule['sha256'] = '0' * 64
    else:
        values = arrays[case.key].transpose(2, 1, 0).copy()
        affine = case.affine_ras.copy()
        if kind == 'label_value': values[3, 3, 3] = 3
        if kind == 'geometry': affine[0, 3] += 1
        if kind == 'float_storage': values = values.astype(np.float32)
        image = nib.Nifti1Image(values, affine); image.header.set_xyzt_units('mm');image.set_qform(affine, 1);image.set_sform(affine, 1);nib.save(image, path)
        rule['sha256'] = core.sha256(path)
    with pytest.raises(core.ValidationError):
        core.validate_job(dataset, job, require_full_correction=True)
