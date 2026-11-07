"""Synthetic prepared-mask package checks; no clinical/anatomical claims."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from correction_inputs import LABEL_MAPPING, canonical, validate_correction_package
from native_mri_package import VerificationError
from package_layout import canonical_relative_folder, checked_case_contents


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_mask(path, case, values=None, origin=None):
    if values is None:
        values = np.zeros(tuple(case['dimensions_xyz'][::-1]), dtype=np.uint8)
        values[0, 1, 2] = 1;values[1, 3, 4] = 2
    image = sitk.GetImageFromArray(values)
    image.SetSpacing(case['spacing_xyz_mm']);image.SetOrigin(origin or case['origin_lps_mm']);image.SetDirection(tuple(np.asarray(case['direction_lps_columns']).ravel()))
    sitk.WriteImage(image, str(path))


@pytest.fixture
def package(tmp_path):
    root = tmp_path / 'SYNTHETIC correction inputs';root.mkdir()
    cases, catalog, layouts = [], {}, {}
    for key, month, side in [('SYNTHETIC_A', 0, 'L'), ('SYNTHETIC_B', 72, 'R')]:
        case = {'case_key': key, 'participant_id': key, 'visit_month': month, 'knee_side': side, 'source_series_key': 'SYNTHETIC_SOURCE_' + key, 'series_instance_uid': 'SYNTHETIC_UID_' + key, 'image_sha256': hashlib.sha256(b'SYNTHETIC MRI MARKER').hexdigest(), 'dimensions_xyz': [5, 6, 3], 'spacing_xyz_mm': [.4, .5, 3.], 'origin_lps_mm': [-20., -30., -40.], 'direction_lps_columns': [[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]]}
        relative = canonical_relative_folder(case);folder = root / relative;folder.mkdir(parents=True)
        (folder / 'case.json').write_text(json.dumps(case));(folder / 'image.nii.gz').write_bytes(b'SYNTHETIC MRI MARKER');(folder / 'slice_review.csv').write_text('slice_index,status\n0,not_reviewed\n1,not_reviewed\n2,not_reviewed\n')
        write_mask(folder / 'starting_mask.nii.gz', case)
        metadata = {'schema_version': 'meniscus_starting_mask/1', **{k: case[k] for k in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')}, 'status': 'unreviewed_automated_prediction', 'prepared_mask_sha256': digest(folder / 'starting_mask.nii.gz'), 'label_mapping': LABEL_MAPPING, 'source_prediction': {'sha256': 'b' * 64, 'pipeline_version': 'SYNTHETIC_PIPELINE_1', 'model_version': 'SYNTHETIC_MODEL_1'}, 'transformation': {'method': 'identity_native_grid', 'original_total_prediction_preserved_before_resampling': True}, 'verification': {'status': 'verified', 'native_grid_match': True, 'independent_target_voxel_mapping_match': True, 'output_labels_valid': True}}
        (folder / 'starting_mask.json').write_text(json.dumps(metadata))
        cases.append(case);catalog[key] = {'case_key': key, 'relative_folder': relative};layouts[key] = 'flat'
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': canonical(sorted((case['case_key'], canonical(case)) for case in cases)), 'protocol': {'version': 'SYNTHETIC_CORRECTION_DRAFT_1', 'status': 'draft'}, 'cases': {}}
    for case in cases:
        relative = catalog[case['case_key']]['relative_folder'];folder = root / relative
        job['cases'][case['case_key']] = {'annotation_mode': 'correction', 'starting_mask': {'path': relative + '/starting_mask.nii.gz', 'sha256': digest(folder / 'starting_mask.nii.gz'), 'source': 'SYNTHETIC source only', 'version': 'SYNTHETIC_PIPELINE_1'}}
    (root / 'correction_job.json').write_text(json.dumps(job))
    return root, cases, catalog, layouts


def mutate_sidecar(package, key, fn):
    root, _, catalog, _ = package;path = root / catalog[key]['relative_folder'] / 'starting_mask.json';value = json.loads(path.read_text());fn(value);path.write_text(json.dumps(value))


def mutate_job(package, fn):
    path = package[0] / 'correction_job.json';value = json.loads(path.read_text());fn(value);path.write_text(json.dumps(value))


def test_complete_correction_extension_reads_without_modifying_source(package):
    root, cases, catalog, layouts = package
    before = {str(p): digest(p) for p in root.rglob('*') if p.is_file()}
    report, files = validate_correction_package(root, cases, catalog, layouts)
    assert report['correction_package_complete'] and report['verified_masks'] == 2
    assert len(files) == 5 and 'correction_job.json' in files
    assert before == {str(p): digest(p) for p in root.rglob('*') if p.is_file()}
    for case in cases:
        folder = root / catalog[case['case_key']]['relative_folder']
        assert checked_case_contents(folder, 'flat', correction=True) == {'image.nii.gz', 'case.json', 'slice_review.csv', 'starting_mask.nii.gz', 'starting_mask.json'}
        with pytest.raises(ValueError):checked_case_contents(folder, 'flat')


@pytest.mark.parametrize('field', ['case_key', 'source_series_key', 'series_instance_uid', 'image_sha256'])
def test_case_and_acquisition_identity_mismatch_fails(package, field):
    mutate_sidecar(package, 'SYNTHETIC_A', lambda x: x.update({field: 'SYNTHETIC_WRONG'}))
    with pytest.raises(VerificationError, match='binding'):validate_correction_package(*package)


def test_job_cannot_omit_case_to_trigger_blank_default(package):
    mutate_job(package, lambda x: x['cases'].pop('SYNTHETIC_A'))
    with pytest.raises(VerificationError, match='every_case'):validate_correction_package(*package)


def test_job_cannot_explicitly_use_blank(package):
    mutate_job(package, lambda x: x['cases']['SYNTHETIC_A'].update(annotation_mode='blank'))
    with pytest.raises(VerificationError, match='blank'):validate_correction_package(*package)


@pytest.mark.parametrize('bad', ['../outside.nii.gz', '/outside.nii.gz', 'Cases\\outside.nii.gz'])
def test_prepared_package_requires_its_exact_portable_case_path(package, bad):
    mutate_job(package, lambda x: x['cases']['SYNTHETIC_A']['starting_mask'].update(path=bad))
    with pytest.raises(VerificationError, match='permission'):validate_correction_package(*package)


def test_pipeline_model_version_mixing_rejected(package):
    mutate_sidecar(package, 'SYNTHETIC_A', lambda x: x['source_prediction'].update(model_version='SYNTHETIC_DIFFERENT_MODEL'))
    with pytest.raises(VerificationError, match='mixed'):validate_correction_package(*package)


def test_unreviewed_prediction_cannot_be_labelled_approved(package):
    mutate_sidecar(package, 'SYNTHETIC_A', lambda x: x.update(status='approved'))
    with pytest.raises(VerificationError, match='unreviewed'):validate_correction_package(*package)


@pytest.mark.parametrize('kind', ['label_value', 'float', 'geometry'])
def test_values_storage_and_native_grid_rejected_even_if_hash_is_refreshed(package, kind):
    root, cases, catalog, layouts = package;case = cases[0];folder = root / catalog[case['case_key']]['relative_folder'];path = folder / 'starting_mask.nii.gz'
    values = np.zeros(tuple(case['dimensions_xyz'][::-1]), dtype=np.float32 if kind == 'float' else np.uint8)
    values[0, 1, 2] = 3 if kind == 'label_value' else 1
    write_mask(path, case, values, origin=[-19., -30., -40.] if kind == 'geometry' else None)
    mutate_sidecar(package, case['case_key'], lambda x: x.update(prepared_mask_sha256=digest(path)))
    mutate_job(package, lambda x: x['cases'][case['case_key']]['starting_mask'].update(sha256=digest(path)))
    with pytest.raises(VerificationError):validate_correction_package(root, cases, catalog, layouts)


def make_unresolved(package):
    root, cases, catalog, _ = package;key = cases[0]['case_key'];folder = root / catalog[key]['relative_folder'];(folder / 'starting_mask.nii.gz').unlink()
    def change(x):
        for name in ('prepared_mask_sha256', 'label_mapping', 'transformation'):x.pop(name)
        x.update(status='unresolved', reason='SYNTHETIC source has no established medial/lateral assignment');x['verification'] = {'status': 'unresolved'}
    mutate_sidecar(package, key, change)
    mutate_job(package, lambda x: x['cases'].update({key: {'annotation_mode': 'correction', 'availability': 'unresolved', 'reason': 'SYNTHETIC source has no established medial/lateral assignment', 'starting_mask': None}}))
    return folder


def test_unresolved_is_explicitly_incomplete_and_never_empty_mask(package):
    folder = make_unresolved(package)
    with pytest.raises((ValueError, VerificationError)):validate_correction_package(*package)
    report, files = validate_correction_package(*package, allow_unresolved=True)
    assert report['verified_masks'] == report['unresolved_cases'] == 1 and not report['correction_package_complete']
    assert not (folder / 'starting_mask.nii.gz').exists()
    assert len(files) == 4


def test_fake_empty_mask_for_unresolved_case_rejected(package):
    folder = make_unresolved(package);write_mask(folder / 'starting_mask.nii.gz', package[1][0], np.zeros((3, 6, 5), dtype=np.uint8))
    with pytest.raises(VerificationError, match='fake_mask'):validate_correction_package(*package, allow_unresolved=True)


def test_unresolved_job_must_block_case(package):
    make_unresolved(package)
    mutate_job(package, lambda x: x['cases']['SYNTHETIC_A'].update(availability='ready'))
    with pytest.raises(VerificationError, match='not_blocked'):validate_correction_package(*package, allow_unresolved=True)
