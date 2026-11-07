"""Minimal reader package assembly and complete byte/content acceptance.
Uses native_mri_package as the single maintained image verification route.
Run first on SCC staging; repeat `--check-only --receipt FILE` after copy locally.
"""
import argparse,csv,hashlib,json,sys
from pathlib import Path
import numpy as np
from native_mri_package import validate_selection,check_nifti,sha256,need
from package_layout import canonical_relative_folder,verify_relative_folder,checked_case_contents
from correction_inputs import validate_correction_package

# Reader-facing schemas are intentionally closed: selection/exposure/partition
# attributes must never leak through an expanded private selection row.
CASE_FIELDS = frozenset('schema_version dataset_version case_key participant_id visit_month original_visit_code source_visit_label knee_side sequence source_series_key series_instance_uid archive_series_number dicom_series_number source_study_date source_series_description dimensions_xyz spacing_xyz_mm origin_lps_mm direction_lps_columns expected_slice_count slice_index_convention image_sha256 annotation_status preparation_verifier'.split())
INDEX_FIELDS = ['participant_id','visit_month','knee_side','case_key','relative_folder','expected_slice_count','annotation_status','image_sha256']
SLICE_FIELDS = ['slice_index','status']

def check_case_schema(case):
 need(set(case)==CASE_FIELDS,'unexpected_or_missing_case_fields')
 need(case['schema_version']=='meniscus_case/1','unsupported_case_schema')
 need(case['sequence']=='sagittal IW fat-suppressed TSE','case_sequence_mismatch')
 need(case['slice_index_convention']=='zero-based along physical volume axis 2; ascending projection on DICOM row-direction cross column-direction; never InstanceNumber','slice_index_convention_mismatch')
 need(bool(case['series_instance_uid']),'missing_case_source_uid')
 shape=np.asarray(case['dimensions_xyz']);spacing=np.asarray(case['spacing_xyz_mm'],dtype=float)
 origin=np.asarray(case['origin_lps_mm'],dtype=float);direction=np.asarray(case['direction_lps_columns'],dtype=float)
 need(shape.shape==(3,) and spacing.shape==(3,) and origin.shape==(3,) and direction.shape==(3,3),'case_geometry_shape_invalid')
 need(np.isfinite(spacing).all() and (spacing>0).all() and np.isfinite(origin).all() and np.isfinite(direction).all(),'case_geometry_invalid')
 need(int(shape[2])==case['expected_slice_count'],'case_slice_count_dimension_mismatch')
 need(np.allclose(direction.T@direction,np.eye(3),atol=1e-5,rtol=0),'case_direction_not_orthonormal')
 affine=np.eye(4);affine[:3,:3]=direction@np.diag(spacing);affine[:3,3]=origin
 return affine

def check_global_sources(cases,reports):
 # Selection rows initially do not know the UIDs: validate the actual exported
 # source UID globally once it has been read from original DICOM.
 validate_selection(cases,len(cases))
 seen_sops=set()
 for report in reports:
  for item in report['source']['source_files']:
   sop=item['sop_instance_uid'];need(bool(sop) and sop not in seen_sops,'source_sop_reused_across_package')
   seen_sops.add(sop)

def validate_catalog_paths(rows,catalog,layout='auto'):
 catalog_by_key={r['case_key']:r for r in catalog}
 need(len(catalog_by_key)==len(catalog),'duplicate_case_index_key')
 need(set(catalog_by_key)=={r['case_key'] for r in rows},'case_index_selection_membership_mismatch')
 paths_by_key={};layouts={}
 for r in rows:
  relative=catalog_by_key[r['case_key']]['relative_folder']
  layouts[r['case_key']]=verify_relative_folder(relative,r)
  need(layout=='auto' or layout==layouts[r['case_key']],'unexpected_package_layout')
  paths_by_key[r['case_key']]=relative
 need(len(set(paths_by_key.values()))==len(rows),'duplicate_case_folder')
 need(len(set(layouts.values()))==1,'mixed_case_folder_layouts')
 return catalog_by_key,paths_by_key,layouts

def main():
 p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--selection',type=Path,required=True);p.add_argument('--reports',type=Path);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--check-only',action='store_true');p.add_argument('--verify-existing',action='store_true',help='Validate existing README/index and write a new receipt without rewriting package files');p.add_argument('--layout',choices=['auto','flat','legacy'],default='auto');p.add_argument('--correction',action='store_true',help='Require explicit correction job and unreviewed automated starting-mask provenance');p.add_argument('--allow-unresolved',action='store_true',help='Record a structurally valid INCOMPLETE correction package with blocked unresolved cases');a=p.parse_args()
 need(not(a.check_only and a.verify_existing),'conflicting_receipt_modes')
 need(not a.allow_unresolved or a.correction,'unresolved_flag_requires_correction_mode')
 need(not a.correction or a.verify_existing or a.check_only,'correction_package_requires_existing_readme_and_index')
 with a.selection.open(newline='') as f:rows=list(csv.DictReader(f))
 validate_selection(rows,250)
 groups={};kl={}
 for r in rows:groups[r['selection_group']]=groups.get(r['selection_group'],0)+1;kl[r['same_visit_kl']]=kl.get(r['same_visit_kl'],0)+1
 need(kl=={str(k):50 for k in range(5)},'kl_targets_mismatch')
 need(groups=={'normal':30,'signal_only':30,'tear_without_maceration':40,'maceration_without_tear':40,'tear_and_maceration':20,'reported_meniscal_surgery':20,'unread':20,'month72':25,'month96':25},'group_targets_mismatch')
 paths_by_key={}
 def rel(r):return paths_by_key.get(r['case_key'],canonical_relative_folder(r,'flat' if a.layout=='auto' else a.layout))
 rows.sort(key=lambda r:(r['participant_id'],int(r['visit_month']),r['knee_side'],r['source_series_key']))
 if not a.check_only and not a.verify_existing:
  need(a.reports is not None,'source_reports_required')
  versions={r.get('dataset_version','OAI_IWFS_250_v1_20261106') for r in rows}
  need(len(versions)==1,'dataset_version_conflict')
  text=('OAI knee MRI annotation inputs\nDataset: '+next(iter(versions))+'\n'+
        ('Folder-layout revision: 1 (legacy folders).\n' if a.layout=='legacy' else 'Folder-layout revision: 2 (flat folders). The scans and dataset identity are unchanged.\n')+
        '250 complete MRI scans from 250 participants. Annotations have not yet been completed.\n\n'
        'Each folder names the OAI participant ID, visit and knee side. M000 is baseline, '
        'M072 is month 72 and M096 is month 96; LEFT and RIGHT identify the knee.\n'
        'image.nii.gz contains the complete acquired MRI scan, with every acquired slice.\n'
        'Keep these source files unchanged during annotation. Do not crop, resize, resample, '
        'normalise, reorder or replace the images.\n'
        'The application saves drafts in a separate local work folder and approved exports '
        'in a separate results folder. Keep those folders separate from this source dataset.\n'
        'case.json identifies the source series and physical grid; slice_review.csv is the original '
        'unreviewed slice table. An absent mask is not confirmed background.\n')
  (a.package/'README.txt').write_text(text)
  with (a.package/'case_index.csv').open('w',newline='') as f:
   fields=INDEX_FIELDS
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for r in rows:
    case=json.loads((a.package/rel(r)/'case.json').read_text());w.writerow({k:({'relative_folder':rel(r),'expected_slice_count':r['native_slices_recorded'],'image_sha256':case['image_sha256']}.get(k,r.get(k,''))) for k in fields})
 with (a.package/'case_index.csv').open(newline='') as f:
  reader=csv.DictReader(f);need(reader.fieldnames==INDEX_FIELDS,'unexpected_case_index_fields');catalog=list(reader)
 need(len(catalog)==250,'case_index_count')
 catalog_by_key,paths_by_key,layouts=validate_catalog_paths(rows,catalog,a.layout)
 expected={'README.txt','case_index.csv'};images=0;slices=0;cases=[];reports=[]
 for r in rows:
  catalog_row=catalog_by_key[r['case_key']]
  folder=a.package/rel(r)
  expected.update(rel(r)+'/'+n for n in ['image.nii.gz','case.json','slice_review.csv'])
  checked_case_contents(folder,layouts[r['case_key']],correction=a.correction,allow_unresolved=a.allow_unresolved)
  case=json.loads((folder/'case.json').read_text());image=folder/'image.nii.gz'
  affine=check_case_schema(case);cases.append(case)
  for k,v in [('case_key',r['case_key']),('participant_id',r['participant_id']),('visit_month',int(r['visit_month'])),('knee_side',r['knee_side']),('source_series_key',r['source_series_key']),('original_visit_code',r['archive_visit_folder']),('source_visit_label',r['source_visit_label']),('archive_series_number',r['archive_series_number']),('source_study_date',r['study_date']),('source_series_description',r['series_description_recorded']),('annotation_status','not_started'),('dataset_version','OAI_IWFS_250_v1_20261106'),('expected_slice_count',int(r['native_slices_recorded']))]:need(case[k]==v,'case_metadata_binding_mismatch_'+k)
  need(catalog_row['case_key']==r['case_key'] and catalog_row['relative_folder']==rel(r) and catalog_row['participant_id']==r['participant_id'] and catalog_row['knee_side']==r['knee_side'] and int(catalog_row['visit_month'])==int(r['visit_month']) and catalog_row['annotation_status']=='not_started' and int(catalog_row['expected_slice_count'])==int(r['native_slices_recorded']),'case_index_binding_mismatch')
  actual=sha256(image);need(actual==case['image_sha256']==catalog_row['image_sha256'],'image_checksum_mismatch')
  if a.reports:
   report=json.loads((a.reports/(r['case_key']+'.json')).read_text())
   reports.append(report)
   need(report['passed'] and report['saved_volume']['all_voxels_match_scaled_original_dicom'] and report['saved_volume']['image_sha256']==actual,'source_verification_missing')
   for field in ('case_key','source_series_key','participant_id','knee_side','source_visit_label','study_date','archive_series_number','series_description_recorded'):
    need(str(report['selection'][field])==str(r[field]),'source_report_binding_mismatch_'+field)
   need(int(report['selection']['visit_month'])==int(r['visit_month']) and int(report['selection']['expected_slice_count'])==int(r['native_slices_recorded']) and report['selection']['original_visit_code']==r['archive_visit_folder'],'source_report_visit_binding_mismatch')
   need(len(report['source']['source_files'])==int(r['native_slices_recorded']),'source_file_count_mismatch')
   need(report['source']['series_instance_uid']==case['series_instance_uid'],'source_uid_mismatch')
  check_nifti(image,case['dimensions_xyz'],affine)
  with (folder/'slice_review.csv').open(newline='') as f:
   reader=csv.DictReader(f);need(reader.fieldnames==SLICE_FIELDS,'unexpected_slice_review_fields');review=list(reader)
  need([x['slice_index'] for x in review]==[str(k) for k in range(int(r['native_slices_recorded']))] and all(x['status']=='not_reviewed' for x in review),'slice_table_mismatch')
  slices+=len(review);images+=1
 check_global_sources(cases,reports)
 correction=None
 if a.correction:
  correction,correction_files=validate_correction_package(a.package,cases,catalog_by_key,layouts,allow_unresolved=a.allow_unresolved)
  expected.update(correction_files)
 need(not any(p.is_symlink() for p in a.package.rglob('*')),'symlink_in_reader_package')
 actual_files={str(p.relative_to(a.package)) for p in a.package.rglob('*') if p.is_file()}
 need(actual_files==expected,'unexpected_or_missing_package_files')
 actual_dirs={str(p.relative_to(a.package)) for p in a.package.rglob('*') if p.is_dir()}
 allowed_dirs=set()
 for r in rows:
  pp=Path(rel(r))
  if (a.package/pp/'annotations').is_dir():pp=pp/'annotations'
  allowed_dirs.update(str(q) for q in [pp,*pp.parents] if str(q)!='.')
 need(actual_dirs==allowed_dirs,'unexpected_or_missing_directories')
 checksums={n:sha256(a.package/n) for n in sorted(expected)}
 receipt={'passed':True,'cases':images,'unique_participants':len({r['participant_id'] for r in rows}),'acquired_slices':slices,'files':len(checksums),'package_bytes':sum((a.package/n).stat().st_size for n in expected),'files_sha256':checksums,'selection_sha256':sha256(a.selection),'scope':'Complete input package and byte integrity; no completed annotations, segmentation validation, training readiness, or test independence implied.'}
 if correction is not None:
  receipt['correction']=correction
  receipt['correction_package_complete']=correction['correction_package_complete']
  receipt['scope']='Original MRI bytes plus explicit unreviewed starting predictions; passed means structural/byte checks, not complete availability when correction_package_complete is false. No completed annotations or anatomical accuracy implied.'
 if a.check_only:
  prior=json.loads(a.receipt.read_text());need(prior==receipt,'copied_package_differs_from_verified_staging')
 else:
  if a.receipt.exists():need(json.loads(a.receipt.read_text())==receipt,'receipt_conflict_use_new_private_path')
  else:a.receipt.write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps({k:v for k,v in receipt.items() if k!='files_sha256'}))
if __name__=='__main__':main()
