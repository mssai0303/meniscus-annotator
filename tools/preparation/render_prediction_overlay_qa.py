"""Read-only full-stack MRI/starting-prediction contact sheets for private QA.

Display windows affect PNG previews only. No MRI/mask values are changed. These
technical views do not constitute expert anatomy review or manual annotations.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import SimpleITK as sitk


def sha256(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):value.update(chunk)
    return value.hexdigest()


def trace_original_foreground(source_prediction, mri_path, prepared_mask):
    """Prove a visible island is inherited from original prediction under NN."""
    paths=list(map(Path,(source_prediction,mri_path,prepared_mask)))
    before={str(p):sha256(p) for p in paths}
    original,image,prepared=[sitk.ReadImage(str(p)) for p in paths]
    source_values=sitk.GetArrayFromImage(original)
    if not np.isin(source_values,[0,1]).all():raise ValueError('original_prediction_is_not_binary')
    mapped=sitk.Resample(original,image,sitk.Transform(),sitk.sitkNearestNeighbor,0,sitk.sitkUInt8)
    expected=sitk.GetArrayFromImage(mapped)>0
    actual=sitk.GetArrayFromImage(prepared)>0
    if not np.array_equal(expected,actual):raise ValueError('prepared_foreground_differs_from_original_binary_nearest_neighbor')
    if any(sha256(Path(p))!=digest for p,digest in before.items()):raise ValueError('input_changed_during_source_trace')
    return {'original_prediction_sha256':before[str(paths[0])],'native_foreground_exactly_equals_original_binary_nearest_neighbor':True,'all_native_foreground_preserved_without_cleanup':True,'nearest_neighbor_source_foreground_by_slice':[int(x.sum()) for x in expected],'inputs_unchanged':True}


def render_case(mri_path, mask_path, case_path, output):
    mri_path,mask_path,case_path,output=map(Path,(mri_path,mask_path,case_path,output))
    if output.exists():raise ValueError('choose_new_private_preview_directory')
    before={str(p):sha256(p) for p in (mri_path,mask_path,case_path,case_path.with_name('slice_review.csv'))}
    case=json.loads(case_path.read_text())
    if before[str(mri_path)]!=case['image_sha256']:raise ValueError('MRI_checksum_disagrees_with_case_identity')
    image=sitk.ReadImage(str(mri_path));mask=sitk.ReadImage(str(mask_path))
    if image.GetSize()!=mask.GetSize():raise ValueError('mask_extent_differs_from_original_MRI')
    for a,b in ((image.GetSpacing(),mask.GetSpacing()),(image.GetOrigin(),mask.GetOrigin()),(image.GetDirection(),mask.GetDirection())):
        if not np.allclose(a,b,atol=1e-6,rtol=0):raise ValueError('mask_grid_differs_from_original_MRI')
    pixels=sitk.GetArrayFromImage(image);labels=sitk.GetArrayFromImage(mask)
    if not np.issubdtype(labels.dtype,np.integer) or not np.isin(labels,[0,1,2]).all():raise ValueError('unsupported_starting_mask_labels')
    if pixels.shape[0]!=case['expected_slice_count']:raise ValueError('acquired_slice_count_mismatch')
    direction=np.asarray(image.GetDirection()).reshape(3,3);spacing=np.asarray(image.GetSpacing());origin=np.asarray(image.GetOrigin())
    centroids={}
    for label,name in ((1,'medial'),(2,'lateral')):
        points=np.argwhere(labels==label)
        if not len(points):raise ValueError('starting_prediction_compartment_absent')
        centroids[name]=(origin+direction@(points.mean(axis=0)[::-1]*spacing)).tolist()
    physical_assignment=(centroids['medial'][0]>centroids['lateral'][0]) if case['knee_side']=='R' else (centroids['medial'][0]<centroids['lateral'][0])
    if not physical_assignment:raise ValueError('label_centroids_disagree_with_existing_anatomical_side_assignment')
    window=np.percentile(pixels,[1,99]);window[1]=max(window[1],window[0]+1)
    side={'L':'LEFT','R':'RIGHT'}[case['knee_side']]
    title=('Baseline' if case['visit_month']==0 else 'Month %d'%case['visit_month'])+' / '+side
    output.mkdir(parents=True)
    pages=[];slice_rows=[]
    for k in range(len(pixels)):
        slice_rows.append({'slice_index':k,'medial_predicted_voxels':int((labels[k]==1).sum()),'lateral_predicted_voxels':int((labels[k]==2).sum()),'physical_slice_origin_lps_mm':image.TransformIndexToPhysicalPoint((0,0,k))})
    for page,start in enumerate(range(0,len(pixels),6),1):
        fig,axes=plt.subplots(3,4,figsize=(12,9),facecolor='black')
        for axis in axes.flat:axis.set_facecolor('black');axis.axis('off')
        indices=list(range(start,min(start+6,len(pixels))))
        for slot,k in enumerate(indices):
            row,column=divmod(slot,2);raw,overlay=axes[row,column*2],axes[row,column*2+1]
            for axis in (raw,overlay):
                axis.imshow(pixels[k],cmap='gray',vmin=window[0],vmax=window[1],origin='upper',aspect=spacing[1]/spacing[0],interpolation='nearest')
            colors=np.zeros((*labels[k].shape,4),dtype=float)
            colors[labels[k]==1]=[1,.12,.12,.5]
            colors[labels[k]==2]=[0,1,1,.5]
            overlay.imshow(colors,origin='upper',aspect=spacing[1]/spacing[0],interpolation='nearest')
            raw.set_title('Slice %d / MRI'%k,color='white',fontsize=8)
            overlay.set_title('Slice %d / M=%d  L=%d'%(k,slice_rows[k]['medial_predicted_voxels'],slice_rows[k]['lateral_predicted_voxels']),color='white',fontsize=8)
        fig.suptitle(title+' — unreviewed automated prediction\nRed = medial; cyan = lateral. Full acquired extent; zero-based physical volume order.\nSOFTWARE PRACTICE QA ONLY — NOT JEFF REVIEW OR ACCEPTED ANNOTATION',color='white',fontsize=10)
        fig.subplots_adjust(left=.005,right=.995,bottom=.005,top=.88,wspace=.02,hspace=.12)
        path=output/('page_%02d.png'%page);fig.savefig(path,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)
        pages.append({'path':str(path),'slice_indices':indices,'sha256':sha256(path)})
    if any(sha256(Path(p))!=digest for p,digest in before.items()):raise ValueError('source_changed_during_read_only_preview')
    result={'case_key':case['case_key'],'participant_id':case['participant_id'],'visit_month':case['visit_month'],'knee_side':case['knee_side'],'source_series_key':case['source_series_key'],'series_instance_uid':case['series_instance_uid'],'MRI_path':str(mri_path),'starting_mask_path':str(mask_path),'source_input_checksums_before_and_after':before,'source_inputs_unchanged':True,'complete_acquired_stack_pages':pages,'slice_count':len(pixels),'dimensions_xyz':image.GetSize(),'spacing_xyz_mm':image.GetSpacing(),'origin_lps_mm':image.GetOrigin(),'direction_lps':image.GetDirection(),'label_centroids_lps_mm':centroids,'physical_anatomical_compartment_order_consistent':physical_assignment,'display_window_only':{'percentiles':[1,99],'vmin':float(window[0]),'vmax':float(window[1])},'all_slices':slice_rows,'review_status':'rendered_pending_human_technical_inspection','limits':'Full-stack technical overlay and physical-side verification only. No anatomical acceptance, expert review, source MRI changes or annotation approval.'}
    (output/'render_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('mri','mask','case-json','output'):parser.add_argument('--'+field,required=True,type=Path)
    args=parser.parse_args();result=render_case(args.mri,args.mask,args.case_json,args.output)
    print(json.dumps({key:result[key] for key in ('visit_month','knee_side','slice_count','source_inputs_unchanged','physical_anatomical_compartment_order_consistent')}))
