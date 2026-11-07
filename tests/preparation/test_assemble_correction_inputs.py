"""Synthetic correction assembly and blocking rules; no participant data."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest
import SimpleITK as sitk

from assemble_correction_inputs import assemble
from correction_inputs import LABEL_MAPPING
from native_mri_package import VerificationError, sha256

REPOSITORY = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('make_synthetic_assembly_fixture', REPOSITORY / 'tools/make_synthetic.py')
synthetic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synthetic)


@pytest.fixture
def inputs(tmp_path):
    source = synthetic.make_synthetic(tmp_path / 'SYNTHETIC MRI-only', layout='flat')
    with (source / 'case_index.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    prepared = tmp_path / 'SYNTHETIC prepared';prepared.mkdir()
    contexts = []
    for row in rows:
        relative = row['relative_folder']; case = json.loads((source / relative / 'case.json').read_text())
        prediction = {'sha256': 'a' * 64, 'pipeline_version': 'SYNTHETIC_RELEASE_1', 'model_version': 'SYNTHETIC_MODEL_1', 'identity': 'SYNTHETIC_PREDICTION_' + case['case_key']}
        context = {field: case[field] for field in ('case_key', 'participant_id', 'visit_month', 'knee_side', 'source_series_key', 'series_instance_uid', 'image_sha256')}
        context['source_prediction'] = prediction
        contexts.append({'case_key': case['case_key'], 'relative_folder': relative, 'categorical_compatibility': 'documented_medial_lateral_assignment', 'unresolved_reason': '', 'context': context})
        folder = prepared / relative;folder.mkdir(parents=True)
        array = np.zeros(case['dimensions_xyz'][::-1], dtype=np.uint8)
        array[0, 2:4, 2:4] = 1;array[-1, 3:5, 3:5] = 2
        image = sitk.GetImageFromArray(array);image.SetOrigin(case['origin_lps_mm']);image.SetSpacing(case['spacing_xyz_mm']);image.SetDirection(tuple(np.asarray(case['direction_lps_columns']).ravel()))
        sitk.WriteImage(image, str(folder / 'starting_mask.nii.gz'), True)
        metadata = {'schema_version': 'meniscus_starting_mask/1', **{key: case[key] for key in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')}, 'prepared_mask_sha256': sha256(folder / 'starting_mask.nii.gz'), 'label_mapping': LABEL_MAPPING, 'status': 'unreviewed_automated_prediction', 'source_prediction': prediction, 'transformation': {'method': 'SYNTHETIC identity native grid'}, 'verification': {'status': 'verified', 'native_grid_match': True, 'independent_target_voxel_mapping_match': True, 'output_labels_valid': True}}
        (folder / 'starting_mask.json').write_text(json.dumps(metadata))
    return source, prepared, contexts


def mark_unresolved(prepared, contexts, index=0):
    row = contexts[index];row['categorical_compatibility'] = 'unresolved';row['unresolved_reason'] = 'SYNTHETIC existing binary prediction has no established anatomical split'
    folder = prepared / row['relative_folder']
    for path in folder.iterdir():path.unlink()
    folder.rmdir()


def test_complete_assembly_preserves_all_original_case_and_index_bytes(inputs, tmp_path):
    source, prepared, contexts = inputs
    before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    prepared_before = {str(path.relative_to(prepared)): path.read_bytes() for path in prepared.rglob('*') if path.is_file()}
    output = tmp_path / 'assembled'
    report = assemble(source, prepared, contexts, output, tmp_path / 'private/report.json', 2)
    assert report['summary']['correction_package_complete']
    assert report['summary']['prepared_masks'] == report['summary']['verified_masks'] == 2
    assert report['summary']['unresolved_cases'] == 0
    assert all((output / name).read_bytes() == value for name, value in before.items() if name != 'README.txt')
    assert all((source / name).read_bytes() == value for name, value in before.items())
    assert all((prepared / name).read_bytes() == value for name, value in prepared_before.items())
    assert (output / 'README.txt').read_bytes() != before['README.txt']
    job = json.loads((output / 'correction_job.json').read_text())
    assert set(job['cases']) == {row['case_key'] for row in contexts}
    assert all(rule['annotation_mode'] == 'correction' and not Path(rule['starting_mask']['path']).is_absolute() for rule in job['cases'].values())
    assert job['protocol']['status'] == 'draft' and 'practice_context' not in job


def test_unresolved_case_is_blocked_without_fabricated_mask_or_blank_fallback(inputs, tmp_path):
    source, prepared, contexts = inputs;mark_unresolved(prepared, contexts)
    output = tmp_path / 'assembled'
    report = assemble(source, prepared, contexts, output, tmp_path / 'private/report.json', 2)
    assert not report['summary']['correction_package_complete']
    assert report['summary']['prepared_masks'] == report['summary']['unresolved_cases'] == 1
    folder = output / contexts[0]['relative_folder']
    assert {path.name for path in folder.iterdir()} == {'image.nii.gz', 'case.json', 'slice_review.csv', 'starting_mask.json'}
    metadata = json.loads((folder / 'starting_mask.json').read_text())
    assert metadata['status'] == 'unresolved' and 'prepared_mask_sha256' not in metadata
    job = json.loads((output / 'correction_job.json').read_text())
    rule = job['cases'][contexts[0]['case_key']]
    assert rule['annotation_mode'] == 'correction' and rule['availability'] == 'unresolved' and rule['starting_mask'] is None
    assert 'INCOMPLETE' in (output / 'README.txt').read_text()


def test_missing_compatible_mask_cannot_silently_become_blank(inputs, tmp_path):
    source, prepared, contexts = inputs
    (prepared / contexts[0]['relative_folder'] / 'starting_mask.nii.gz').unlink()
    with pytest.raises(VerificationError, match='prepared_files_missing'):
        assemble(source, prepared, contexts, tmp_path / 'assembled', tmp_path / 'private/report.json')
    assert not (tmp_path / 'assembled').exists()


@pytest.mark.parametrize('change', ['wrong_source', 'mixed_model', 'duplicate', 'unsafe_folder'])
def test_context_and_prepared_identity_errors_rejected_before_copy(inputs, tmp_path, change):
    source, prepared, contexts = inputs
    if change == 'wrong_source':contexts[0]['context']['source_series_key'] = 'SYNTHETIC_WRONG_SOURCE'
    if change == 'mixed_model':contexts[0]['context']['source_prediction']['model_version'] = 'SYNTHETIC_OTHER_MODEL'
    if change == 'duplicate':contexts.append(copy.deepcopy(contexts[0]))
    if change == 'unsafe_folder':contexts[0]['relative_folder'] = '../elsewhere'
    with pytest.raises(VerificationError):assemble(source, prepared, contexts, tmp_path / 'assembled', tmp_path / 'private/report.json')
    assert not (tmp_path / 'assembled').exists()


def test_source_annotation_content_preserved_and_rejected(inputs, tmp_path):
    source, prepared, contexts = inputs
    folder = source / contexts[0]['relative_folder'] / 'annotations';folder.mkdir();existing = folder / 'SYNTHETIC_EXISTING_WORK.txt';existing.write_text('preserve')
    with pytest.raises(ValueError):assemble(source, prepared, contexts, tmp_path / 'assembled', tmp_path / 'private/report.json')
    assert existing.read_text() == 'preserve'
    assert not (tmp_path / 'assembled').exists()


def test_unresolved_case_cannot_hide_a_fake_mask(inputs, tmp_path):
    source, prepared, contexts = inputs;contexts[0]['categorical_compatibility'] = 'unresolved';contexts[0]['unresolved_reason'] = 'SYNTHETIC no split'
    with pytest.raises(VerificationError, match='unresolved_case_has_unexpected_prepared_content'):
        assemble(source, prepared, contexts, tmp_path / 'assembled', tmp_path / 'private/report.json')


def test_assembler_refuses_existing_output_and_private_report_in_package(inputs, tmp_path):
    source, prepared, contexts = inputs;output = tmp_path / 'assembled';output.mkdir()
    with pytest.raises(VerificationError, match='already_exists'):
        assemble(source, prepared, contexts, output, tmp_path / 'private/report.json')
    output.rmdir()
    with pytest.raises(VerificationError, match='private_report_inside'):
        assemble(source, prepared, contexts, output, output / 'private.json')


def test_private_report_cannot_mutate_prepared_input_tree(inputs, tmp_path):
    source, prepared, contexts = inputs
    with pytest.raises(VerificationError, match='private_report_inside_prepared'):
        assemble(source, prepared, contexts, tmp_path / 'assembled', prepared / 'private.json')
    assert not (tmp_path / 'assembled').exists() and not (prepared / 'private.json').exists()
