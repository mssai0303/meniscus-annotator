"""Scheduler batch for frozen matched predictions after a two-case practice gate.

No inference, new selection, MRI export or anatomical postprocessing. Inputs are
read-only. Successful existing outputs are verified before being resumed.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import SimpleITK as sitk
from prepare_starting_mask import prepare, sha256, StartingMaskError
from source_operation_gate import require_source_permission


def initialize():
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)


def one(task):
    record, workspace = task
    workspace = Path(workspace)
    base = workspace / 'private/correction_preparation_20261106'
    folder = base / 'prepared' / record['relative_folder']
    report_path = base / 'verification' / (record['case_key'] + '.json')
    try:
        if report_path.exists():
            report = json.loads(report_path.read_text())
            assert report['passed'] and report['source_context'] == record['context'], 'resume_context_changed'
            assert sha256(folder / 'starting_mask.nii.gz') == report['sidecar']['prepared_mask_sha256'], 'resume_mask_changed'
            assert json.loads((folder / 'starting_mask.json').read_text()) == report['sidecar'], 'resume_sidecar_changed'
            assert sha256(record['native_mri_scc_path']) == record['context']['image_sha256'], 'resume_MRI_changed'
            assert sha256(record['source_prediction_scc_path']) == record['context']['source_prediction']['sha256'], 'resume_prediction_changed'
        else:
            report = prepare(record['native_mri_scc_path'], record['source_prediction_scc_path'], record['context'], folder / 'starting_mask.nii.gz', folder / 'starting_mask.json', report_path)
        assert report['source_label_counts']['1'] + report['source_label_counts']['2'] == record['source_foreground_voxels'], 'source_union_count_differs_from_pipeline'
        for value in ('1', '2'):
            assert abs(report['source_label_volumes_mm3'][value] - record['source_label_volumes_mm3'][value]) < .001, 'source_compartment_volume_differs_from_pipeline'
        return {'case_key': record['case_key'], 'passed': True}
    except Exception as error:
        return {'case_key': record['case_key'], 'passed': False, 'error': str(error) if isinstance(error, (StartingMaskError, AssertionError)) else type(error).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--contexts', type=Path, required=True)
    parser.add_argument('--practice-gate', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=1)
    a = parser.parse_args()
    if not os.environ.get('JOB_ID'):
        raise ValueError('substantial_mask_conversion_requires_scheduler')
    gate = json.loads(a.practice_gate.read_text())
    assert gate['passed'] and gate['all_original_inputs_unchanged'], 'two_case_gate_not_passed'
    assert gate['converter_sha256'] == sha256(Path(__file__).with_name('prepare_starting_mask.py')), 'converter_changed_after_practice'
    records = json.loads(a.contexts.read_text())
    assert gate['contexts_sha256'] == sha256(a.contexts), 'matched_contexts_changed'
    assert len(records) == len({r['case_key'] for r in records}) == 250
    require_source_permission(a.workspace, [r['context'] for r in records])
    practice = set(gate['practice_case_keys'])
    pending = [r for r in records if r['categorical_compatibility'] == 'documented_medial_lateral_assignment' and r['case_key'] not in practice]
    assert len(practice) == 2 and len(pending) == 247, 'unexpected_frozen_batch_membership'
    workers = min(a.workers, int(os.environ.get('NSLOTS', '1')), 4)
    assert workers > 0
    results = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'), initializer=initialize) as pool:
        futures = [pool.submit(one, (record, str(a.workspace))) for record in pending]
        for future in as_completed(futures):
            results.append(future.result())
            print('Starting masks verified:', sum(r['passed'] for r in results), 'of', len(pending), '; failures:', sum(not r['passed'] for r in results), flush=True)
    out = a.workspace / 'private/correction_preparation_20261106'
    result = {'passed': sum(r['passed'] for r in results), 'failed': sum(not r['passed'] for r in results), 'expected': len(pending), 'workers': workers, 'cases': results}
    (out / 'bulk_result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
