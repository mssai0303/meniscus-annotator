"""Synthetic read-only full-stack preview/source-trace mechanics."""
import json
import numpy as np
import SimpleITK as sitk
import pytest
pytest.importorskip('matplotlib.pyplot', reason='Optional preview dependencies unavailable', exc_type=ImportError)
from render_prediction_overlay_qa import render_case,trace_original_foreground,sha256


def fixture(tmp_path):
    pixels=np.arange(3*6*8,dtype=np.int16).reshape(3,6,8)
    image=sitk.GetImageFromArray(pixels);image.SetSpacing((.5,.5,3));image.SetOrigin((-30.,0.,0.));image.SetDirection((0.,0.,1.,1.,0.,0.,0.,1.,0.))
    labels=np.zeros_like(pixels,dtype=np.uint8);labels[0,2:4,2:4]=2;labels[2,2:4,2:4]=1
    mask=sitk.GetImageFromArray(labels);mask.CopyInformation(image)
    mri_path,mask_path=tmp_path/'image.nii.gz',tmp_path/'starting_mask.nii.gz'
    sitk.WriteImage(image,str(mri_path));sitk.WriteImage(mask,str(mask_path))
    case={'case_key':'SYNTHETIC_CASE','participant_id':'SYNTHETIC_ID','visit_month':0,'knee_side':'R','source_series_key':'SYNTHETIC_SOURCE','series_instance_uid':'SYNTHETIC_UID','expected_slice_count':3,'image_sha256':sha256(mri_path)}
    case_path=tmp_path/'case.json';case_path.write_text(json.dumps(case));(tmp_path/'slice_review.csv').write_text('slice_index,status\n0,not_reviewed\n1,not_reviewed\n2,not_reviewed\n')
    return mri_path,mask_path,case_path


def test_all_slices_in_full_extent_and_no_source_write(tmp_path):
    mri,mask,case=fixture(tmp_path)
    result=render_case(mri,mask,case,tmp_path/'private_preview')
    assert result['source_inputs_unchanged'] and result['physical_anatomical_compartment_order_consistent']
    assert result['complete_acquired_stack_pages'][0]['slice_indices']==[0,1,2]
    assert result['dimensions_xyz']==(8,6,3)
    assert result['review_status']=='rendered_pending_human_technical_inspection'


def test_wrong_compartment_order_is_rejected(tmp_path):
    mri,mask,case=fixture(tmp_path);data=json.loads(case.read_text());data['knee_side']='L';case.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='label_centroids_disagree'):
        render_case(mri,mask,case,tmp_path/'private_preview')


def test_source_foreground_trace_does_not_remove_island(tmp_path):
    mri,mask,case=fixture(tmp_path)
    original=sitk.ReadImage(str(mask));a=sitk.GetArrayFromImage(original)>0;binary=sitk.GetImageFromArray(a.astype(np.uint8));binary.CopyInformation(original)
    source=tmp_path/'original_binary.nii.gz';sitk.WriteImage(binary,str(source))
    result=trace_original_foreground(source,mri,mask)
    assert result['native_foreground_exactly_equals_original_binary_nearest_neighbor']
    assert result['nearest_neighbor_source_foreground_by_slice']==[4,0,4]
