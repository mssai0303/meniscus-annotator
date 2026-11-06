"""Scheduling/aggregation checks using synthetic workers; opens no source image."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import SimpleITK as sitk
import run_export_batch as runner

def fake_case(task):
    ordinal,row,marker=task
    Path(marker).write_text(json.dumps({'pid':os.getpid(),'threads':sitk.ProcessObject.GetGlobalDefaultNumberOfThreads()}))
    time.sleep(.15*(1+ordinal%2))
    if ordinal==2:
        raise RuntimeError('synthetic process task exception')
    if ordinal==0:
        return {'ordinal':ordinal,'passed':False,'error':'synthetic_verification_failure','error_type':'VerificationError'}
    return {'ordinal':ordinal,'passed':True,'resumed':ordinal==1}

class ParallelRunner(unittest.TestCase):
    def test_slot_cap_and_invalid_allocation(self):
        self.assertEqual(runner.workers_from_slots('1'),1)
        self.assertEqual(runner.workers_from_slots('4'),4)
        self.assertEqual(runner.workers_from_slots('16'),4)
        with self.assertRaises(ValueError):runner.workers_from_slots('0')
    def test_parallel_completion_exception_and_deterministic_failure_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks=tuple((k,{'case_key':'SYNTHETIC_'+str(k)},str(Path(tmp)/str(k))) for k in range(8))
            passed,failed=runner.run_tasks(tasks,4,worker=fake_case)
            self.assertEqual(passed,6)
            self.assertEqual(failed,[{'case_key':'SYNTHETIC_0','error':'synthetic_verification_failure'},{'case_key':'SYNTHETIC_2','error':'RuntimeError'}])
            markers=[json.loads((Path(tmp)/str(k)).read_text()) for k in range(8)]
            self.assertTrue(all(m['threads']==1 for m in markers))
            self.assertLessEqual(len({m['pid'] for m in markers}),4)
            self.assertGreaterEqual(len({m['pid'] for m in markers}),2)
    def row(self):
        return dict(participant_id='SYNTHETIC',visit_month=0,knee_side='L',case_key='SYNTHETIC_CASE',source_series_key='SYNTHETIC_SOURCE',original_visit_code='0.E.1',study_date='20000101',archive_series_number='ARCHIVE',relative_folder='Cases/OAI_SYNTHETIC/M000/LEFT/series_SYNTHETIC_SOURCE')
    def test_path_preflight_canonical_and_permission_gate(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'require_source_permission') as gate:
            rows=[self.row()];tasks=runner.prepare_tasks(Path(tmp),'synthetic',rows)
            gate.assert_called_once_with(Path(tmp),rows)
            self.assertEqual(len(tasks),1)
            self.assertIsInstance(tasks,tuple)
            self.assertEqual(tasks[0][1],rows[0]);self.assertIsNot(tasks[0][1],rows[0])
    def test_flat_layout_preflight_preserves_source_binding(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'require_source_permission'):
            row=self.row();row['relative_folder']='Cases/OAI_SYNTHETIC_M000_LEFT'
            task=runner.prepare_tasks(Path(tmp),'synthetic',[row])[0]
            self.assertEqual(task[1],row)
            self.assertTrue(task[3].endswith(row['relative_folder']))
            self.assertTrue(task[2].endswith('/0.E.1/SYNTHETIC/20000101/ARCHIVE'))
    def test_verified_case_resume_after_layout_only_move_preserves_report(self):
        import shutil
        import test_native_mri_package as fixture
        from package_layout import canonical_relative_folder
        generated=fixture.NativeInputs();generated.setUp()
        try:
            row=generated.row
            row['relative_folder']=canonical_relative_folder(row,'legacy')
            generated.export()
            report=generated.root/'private/report.json';before=report.read_bytes()
            folder=generated.root/'flat_case';shutil.move(str(generated.root/'case'),str(folder))
            (folder/'annotations').rmdir()
            changed=dict(row,relative_folder=canonical_relative_folder(row,'flat'))
            result=runner.process_case((0,changed,str(generated.src),str(folder),str(report)))
            self.assertTrue(result['passed']);self.assertTrue(result['resumed'])
            self.assertEqual(report.read_bytes(),before)
            wrong=dict(changed,participant_id='SYNTHETIC_WRONG')
            self.assertFalse(runner.process_case((0,wrong,str(generated.src),str(folder),str(report)))['passed'])
        finally:generated.tearDown()
    def test_path_preflight_rejects_redirected_folder_and_unsafe_token(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'require_source_permission'):
            row=self.row();row['relative_folder']='../outside'
            with self.assertRaisesRegex(ValueError,'unsafe_relative'):runner.prepare_tasks(Path(tmp),'synthetic',[row])
            row=self.row();row['archive_series_number']='../other'
            with self.assertRaisesRegex(ValueError,'unsafe_case_source'):runner.prepare_tasks(Path(tmp),'synthetic',[row])
    def test_path_preflight_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp,tempfile.TemporaryDirectory() as outside,patch.object(runner,'require_source_permission'):
            root=Path(tmp);(root/'staging').mkdir();(root/'staging/Cases').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'outside_staging'):runner.prepare_tasks(root,'synthetic',[self.row()])

if __name__=='__main__':unittest.main(verbosity=2)
