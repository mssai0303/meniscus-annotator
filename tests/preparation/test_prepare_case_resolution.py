"""Synthetic physical-plane case resolution; no participant identities or anatomy."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from native_mri_package import sha256
from prepare_case_resolution import (ASSIGNMENT_STATUS, METHOD, partition_by_physical_plane,
                                     prepare)
from prepare_starting_mask import StartingMaskError, affine_lps


def write_image(path, array, origin, direction, spacing):
    image = sitk.GetImageFromArray(array);image.SetOrigin(origin);image.SetDirection(tuple(direction.ravel()));image.SetSpacing(spacing)
    sitk.WriteImage(image, str(path), True)
    return image


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / 'SYNTHETIC MRI';root.mkdir()
    origin = np.array([20., -10., 10.]);direction = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    mri = root / 'image.nii.gz'
    reference = write_image(mri, np.arange(10*20*20, dtype=np.int16).reshape(10, 20, 20), origin, direction, (.5, .5, 1.))
    binary = np.zeros((20, 20, 20), dtype=np.uint8)
    binary[6:10, 2:6, 2:6] = 1
    binary[8:12, 2:6, 12:16] = 1  # Overlaps the other group's K range: no array-K cut can separate them.
    binary[7, 0, 0] = 1  # A tiny original fragment remains in source foreground.
    prediction = tmp_path / 'SYNTHETIC binary.nii.gz'
    original = write_image(prediction, binary, origin, direction, (.5, .5, .5))
    context = {'case_key': 'SYNTHETIC_CASE', 'source_series_key': 'SYNTHETIC_SERIES', 'series_instance_uid': 'SYNTHETIC_UID', 'image_sha256': sha256(mri), 'knee_side': 'L', 'source_grid_dimensions_xyz': list(original.GetSize()), 'source_prediction': {'sha256': sha256(prediction), 'pipeline_version': 'SYNTHETIC_PIPELINE', 'model_version': 'SYNTHETIC_MODEL', 'identity': 'SYNTHETIC_BINARY'}, 'existing_split': {'split_method': 'whole', 'split_cut_plane': ''}}
    case = {key: context[key] for key in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256', 'knee_side')}
    case.update(dimensions_xyz=list(reference.GetSize()),spacing_xyz_mm=list(reference.GetSpacing()),origin_lps_mm=origin.tolist(),direction_lps_columns=direction.tolist())
    (root / 'case.json').write_text(json.dumps(case))
    evidence = {'schema_version': 'meniscus_case_anatomy_evidence/1', **{key: context[key] for key in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')}, 'source_prediction_sha256': sha256(prediction), 'supports_provisional_region_attribution': True, 'expert_approval': False, 'landmarks': {'fibular_head': 'SYNTHETIC explicit landmark statement only; not real anatomy.', 'both_tibiofemoral_compartments': 'SYNTHETIC two-region evidence.', 'intercondylar_notch': 'SYNTHETIC separating empty region.'}, 'attention_native_slices': [3, 4], 'attention_reason': 'SYNTHETIC tiny fragments remain unreviewed and require later expert inspection.'}
    evidence_path = tmp_path / 'private/evidence.json';evidence_path.parent.mkdir();evidence_path.write_text(json.dumps(evidence))
    normal = np.array([1., 1., 0.])/np.sqrt(2)
    assignment = {'schema_version': 'meniscus_case_compartment_assignment/1', 'method': METHOD, **{key: context[key] for key in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')}, 'source_prediction_sha256': sha256(prediction), 'physical_plane_lps': {'normal': normal.tolist(), 'point_mm': (origin + [4., 4., 2.]).tolist(), 'medial_side': 'negative'}, 'evidence': {'path': 'evidence.json', 'sha256': sha256(evidence_path)}, 'original_pipeline_assignment': {'status': 'ok_whole', 'split_method': 'whole', 'reason': 'SYNTHETIC original pipeline did not assign compartments'}, 'anatomical_assignment_status': ASSIGNMENT_STATUS, 'expert_approval': False, 'attention_native_slices': [3, 4]}
    assignment_path = tmp_path / 'private/assignment.json';assignment_path.write_text(json.dumps(assignment))
    return mri,prediction,context,assignment_path,evidence_path,binary,reference,original


def execute(values, tmp_path):
    return prepare(values[0],values[1],values[2],values[3],tmp_path/'reader/starting_mask.nii.gz',tmp_path/'reader/starting_mask.json',tmp_path/'private/report.json')


def test_physical_plane_not_source_array_K_and_all_foreground_preserved(inputs, tmp_path):
    before = {path:path.read_bytes() for path in (inputs[0],inputs[1],inputs[0].parent/'case.json',inputs[3],inputs[4])}
    report = execute(inputs,tmp_path)
    output = sitk.ReadImage(str(tmp_path/'reader/starting_mask.nii.gz'));array = sitk.GetArrayFromImage(output)
    original_native = sitk.GetArrayFromImage(sitk.Resample(inputs[7],inputs[6],sitk.Transform(3,sitk.sitkIdentity),sitk.sitkNearestNeighbor,0,sitk.sitkUInt8))
    assert np.array_equal(array>0,original_native>0)
    assert (array[4]==1).any() and (array[4]==2).any()
    assert report['source_label_counts']['1']+report['source_label_counts']['2']==int(inputs[5].sum())
    assert output.GetSize()==inputs[6].GetSize() and np.allclose(output.GetOrigin(),inputs[6].GetOrigin()) and np.allclose(output.GetDirection(),inputs[6].GetDirection()) and np.allclose(output.GetSpacing(),inputs[6].GetSpacing())
    assert report['saved_mask_header']['spatial_units']=='mm'
    assert report['sidecar']['verification']['anatomical_assignment_status']==ASSIGNMENT_STATUS and report['sidecar']['verification']['expert_approval'] is False
    assert 'existing_compartment_assignment' not in report['sidecar']['transformation']
    assert report['sidecar']['transformation']['original_pipeline_assignment']['status']=='ok_whole'
    assert all(path.read_bytes()==payload for path,payload in before.items())


def test_opposite_normal_with_corresponding_sign_keeps_same_physical_labels(inputs):
    assignment=json.loads(inputs[3].read_text());plane=assignment['physical_plane_lps'];normal=np.array(plane['normal']);point=np.array(plane['point_mm'])
    first,_=partition_by_physical_plane(inputs[5],affine_lps(inputs[7]),normal,point,'negative','L')
    second,_=partition_by_physical_plane(inputs[5],affine_lps(inputs[7]),-normal,point,'positive','L')
    assert np.array_equal(first,second)


@pytest.mark.parametrize('field',['case_key','image_sha256','source_prediction_sha256'])
def test_assignment_wrong_identity_or_hash_rejected(inputs,tmp_path,field):
    value=json.loads(inputs[3].read_text());value[field]='SYNTHETIC_WRONG';inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='identity_mismatch|checksum_mismatch'):execute(inputs,tmp_path)
    assert not (tmp_path/'reader/starting_mask.nii.gz').exists()


def test_evidence_sha_and_required_landmarks_not_bypassed(inputs,tmp_path):
    evidence=json.loads(inputs[4].read_text());evidence['landmarks'].pop('fibular_head');inputs[4].write_text(json.dumps(evidence))
    with pytest.raises(StartingMaskError,match='evidence_checksum'):execute(inputs,tmp_path)
    value=json.loads(inputs[3].read_text());value['evidence']['sha256']=sha256(inputs[4]);inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='landmark_rationale_incomplete'):execute(inputs,tmp_path)


def test_plane_through_positive_voxel_support_is_rejected(inputs,tmp_path):
    value=json.loads(inputs[3].read_text());value['physical_plane_lps']['point_mm']=[23.5,-8.5,11.5];inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='empty_foreground_gap'):execute(inputs,tmp_path)


def test_wrong_medial_sign_rejected_against_LPS_side(inputs,tmp_path):
    value=json.loads(inputs[3].read_text());value['physical_plane_lps']['medial_side']='positive';inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='conflicts_with_LPS'):execute(inputs,tmp_path)


def test_existing_pipeline_cut_cannot_be_overwritten(inputs,tmp_path):
    inputs[2]['existing_split']={'split_method':'april','split_cut_plane':10}
    with pytest.raises(StartingMaskError,match='replace_an_existing'):execute(inputs,tmp_path)


def test_expert_approval_or_missing_attention_evidence_rejected(inputs,tmp_path):
    value=json.loads(inputs[3].read_text());value['expert_approval']=True;inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='remain_provisional'):execute(inputs,tmp_path)
    value['expert_approval']=False;value['attention_native_slices']=[];inputs[3].write_text(json.dumps(value))
    with pytest.raises(StartingMaskError,match='attention_slices_required'):execute(inputs,tmp_path)


def test_input_MRI_and_original_prediction_checksums_remain_bound(inputs,tmp_path):
    inputs[2]['source_prediction']['sha256']='0'*64
    with pytest.raises(StartingMaskError,match='prediction_provenance_mismatch'):execute(inputs,tmp_path)


def test_outputs_not_overwritten(inputs,tmp_path):
    execute(inputs,tmp_path);payload=(tmp_path/'reader/starting_mask.nii.gz').read_bytes()
    with pytest.raises(StartingMaskError,match='outputs_already_exist'):execute(inputs,tmp_path)
    assert (tmp_path/'reader/starting_mask.nii.gz').read_bytes()==payload
