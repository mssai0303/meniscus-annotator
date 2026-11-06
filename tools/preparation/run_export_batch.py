"""SCC acquired-grid batch runner; independent cases use at most four allocated slots.
Resume only complete checked case bytes. Paths and permission gates are fixed before
workers start. Workers write only their own case folder and private report.
"""
import csv
import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import re
import sys

import SimpleITK as sitk
from native_mri_package import export_case,sha256,check_nifti,validate_selection,VerificationError
from source_operation_gate import require_source_permission
from assemble_and_check_package import check_case_schema,SLICE_FIELDS
from package_layout import verify_relative_folder,checked_case_contents

R=Path(os.environ.get('MRI_PREPARATION_WORKSPACE',str(Path(__file__).resolve().parents[1])))

def configure_worker():
    # One independent case per scheduler slot; ITK must not create nested teams.
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)

def workers_from_slots(value=None):
    slots=int(os.environ.get('NSLOTS','1') if value is None else value)
    if slots<1:
        raise ValueError('invalid_scheduler_slot_count')
    return min(slots,4)

def checked_under(path, parent):
    try:
        relative=path.relative_to(parent)
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        raise ValueError('source_or_output_path_outside_staging')
    cursor=parent
    for part in relative.parts:
        cursor=cursor/part
        if cursor.is_symlink():
            raise ValueError('symlink_in_source_or_output_path')
    return str(path)

def prepare_tasks(root,batch,rows):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',batch):
        raise ValueError('unsafe_batch_name')
    validate_selection(rows)
    require_source_permission(root,rows)
    staging=root/'staging';verification=root/'private/verification'
    source_root=root/'private/work'/batch/'x/MRIs'
    tasks=[];folders=set();reports=set();sources=set()
    for i,row in enumerate(rows):
        # All paths are constructed once, validated, then passed by value to the
        # workers. A selected row cannot redirect another worker's output.
        for field in ('case_key','participant_id','original_visit_code','study_date','archive_series_number','source_series_key'):
            value=str(row[field])
            if not re.fullmatch(r'[A-Za-z0-9._-]+',value) or value in ('.','..'):
                raise ValueError('unsafe_case_source_token')
        verify_relative_folder(row['relative_folder'],row)
        expected=row['relative_folder']
        folder=checked_under(staging/expected,staging)
        report=checked_under(verification/(row['case_key']+'.json'),verification)
        source=checked_under(source_root/row['original_visit_code']/row['participant_id']/row['study_date']/row['archive_series_number'],source_root)
        if folder in folders or report in reports or source in sources:
            raise ValueError('case_paths_reused_in_batch')
        folders.add(folder);reports.add(report);sources.add(source)
        tasks.append((i,dict(row),source,folder,report))
    return tuple(tasks)

def process_case(task):
    i,row,source,folder,report=task
    source=Path(source);folder=Path(folder);report=Path(report)
    try:
        resumed=report.exists()
        if resumed:
            old=json.loads(report.read_text())
            # Folder organisation is not source identity. Retain every other
            # frozen field, and never rewrite the historical source report.
            without_path=lambda value:{key:item for key,item in value.items() if key!='relative_folder'}
            assert old['passed'] and without_path(old['selection'])==without_path(row),'resume_binding_mismatch'
            assert sha256(folder/'image.nii.gz')==old['saved_volume']['image_sha256'],'resume_image_checksum_mismatch'
            case=json.loads((folder/'case.json').read_text())
            affine=check_case_schema(case)
            for field in ('case_key','participant_id','knee_side','source_series_key','original_visit_code','source_visit_label','dataset_version'):
                assert str(case[field])==str(row[field]),'resume_case_binding_mismatch'
            assert int(case['visit_month'])==int(row['visit_month']) and int(case['expected_slice_count'])==int(row['expected_slice_count']),'resume_case_visit_mismatch'
            assert case['series_instance_uid']==old['source']['series_instance_uid'] and case['image_sha256']==old['saved_volume']['image_sha256'],'resume_source_uid_mismatch'
            check_nifti(folder/'image.nii.gz',case['dimensions_xyz'],affine)
            with (folder/'slice_review.csv').open(newline='') as f:
                reader=csv.DictReader(f);assert reader.fieldnames==SLICE_FIELDS,'resume_slice_schema_mismatch';review=list(reader)
            assert [r['slice_index'] for r in review]==[str(k) for k in range(int(row['expected_slice_count']))] and all(r['status']=='not_reviewed' for r in review),'resume_slice_review_mismatch'
            checked_case_contents(folder,verify_relative_folder(row['relative_folder'],row))
        else:
            export_case(source,row,folder,report)
        return {'ordinal':i,'passed':True,'resumed':resumed}
    except Exception as exc:
        return {'ordinal':i,'passed':False,'error':str(exc) if isinstance(exc,VerificationError) else type(exc).__name__,'error_type':type(exc).__name__}

def run_tasks(tasks,max_workers,worker=process_case):
    """Aggregate in parent only; failed rows retain original deterministic order."""
    passed=0;failed=[]
    with ProcessPoolExecutor(max_workers=max_workers,mp_context=multiprocessing.get_context('spawn'),initializer=configure_worker) as pool:
        futures={pool.submit(worker,task):task for task in tasks}
        for future in as_completed(futures):
            task=futures[future];ordinal,row=task[:2]
            try:
                result=future.result()
                if result['ordinal']!=ordinal:
                    raise ValueError('worker_result_binding_mismatch')
            except Exception as exc:
                result={'ordinal':ordinal,'passed':False,'error':type(exc).__name__,'error_type':type(exc).__name__}
            if result['passed']:
                if result.get('resumed'):
                    print('Verified existing',ordinal+1,flush=True)
                passed+=1
                print('Cases verified:',passed,'of',len(tasks),flush=True)
            else:
                failed.append((ordinal,{'case_key':row['case_key'],'error':result['error']}))
                print('Case ordinal',ordinal+1,'failed',result['error_type'],flush=True)
    return passed,[row for _,row in sorted(failed,key=lambda item:item[0])]

def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=1 or not re.fullmatch(r'[A-Za-z0-9_-]+',args[0]):
        raise ValueError('one_safe_batch_name_required')
    batch=args[0]
    batch_path=R/'private'/('batch_'+batch+'.json')
    raw=batch_path.read_bytes();rows=json.loads(raw)
    freeze=json.loads((R/'results/export_batch_freeze.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=freeze['batches'][batch]['sha256']:
        raise ValueError('frozen_batch_checksum_mismatch')
    tasks=prepare_tasks(R,batch,rows)
    workers=workers_from_slots()
    print('Export workers:',workers,'cases:',len(tasks),flush=True)
    passed,failed=run_tasks(tasks,workers)
    (R/'results'/batch/'batch_result.json').write_text(json.dumps({'passed':passed,'failed':len(failed),'total':len(rows),'workers':workers},indent=2)+'\n')
    failures=R/'private'/('failures_'+batch+'.json')
    failures.write_text(json.dumps(failed,indent=2)+'\n');failures.chmod(0o600)
    return 1 if failed else 0

if __name__=='__main__':
    sys.exit(main())
