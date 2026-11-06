"""Acceptance regression checks for reader privacy and source identity; no anatomy claim."""
import json
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

import assemble_and_check_package as a
import native_mri_package as m
import test_native_mri_package as fixture
from source_operation_gate import require_source_permission,file_sha256

class ReaderSchema(unittest.TestCase):
    setUp=fixture.NativeInputs.setUp
    tearDown=fixture.NativeInputs.tearDown
    export=fixture.NativeInputs.export
    def test_reader_schema_generated_case_and_nifti_agree(self):
        self.export();case=json.loads((self.root/'case/case.json').read_text())
        affine=a.check_case_schema(case)
        m.check_nifti(self.root/'case/image.nii.gz',case['dimensions_xyz'],affine)
    def test_reader_schema_rejects_private_sampling_and_partition_fields(self):
        self.export();case=json.loads((self.root/'case/case.json').read_text())
        for field in ['selection_group','same_visit_kl','dataset_role_working','documented_uses','practice_reserved']:
            leaked=dict(case,**{field:'private'})
            with self.assertRaisesRegex(m.VerificationError,'case_fields'):a.check_case_schema(leaked)
    def test_reader_schema_rejects_geometry_not_matching_image(self):
        self.export();case=json.loads((self.root/'case/case.json').read_text())
        case['origin_lps_mm'][0]+=.1
        with self.assertRaisesRegex(m.VerificationError,'transform_differs_from_source'):
            m.check_nifti(self.root/'case/image.nii.gz',case['dimensions_xyz'],a.check_case_schema(case))

class SourceBinding(unittest.TestCase):
    def rows(self):
        return [dict(participant_id='SYNTHETIC_A',visit_month=0,knee_side='L',case_key='A',source_series_key='sourceA',series_instance_uid='1.2.3'),dict(participant_id='SYNTHETIC_B',visit_month=72,knee_side='R',case_key='B',source_series_key='sourceB',series_instance_uid='1.2.4')]
    def reports(self):return [dict(source=dict(source_files=[dict(sop_instance_uid='1.2.3.1')])),dict(source=dict(source_files=[dict(sop_instance_uid='1.2.4.1')]))]
    def test_distinct_source_uids_pass(self):a.check_global_sources(self.rows(),self.reports())
    def test_uid_reused_for_other_participant_fails(self):
        rows=self.rows();rows[1]['series_instance_uid']=rows[0]['series_instance_uid']
        with self.assertRaisesRegex(m.VerificationError,'source_key_conflicting_identity'):a.check_global_sources(rows,self.reports())
    def test_sop_reused_across_series_fails(self):
        reports=self.reports();reports[1]['source']['source_files'][0]['sop_instance_uid']='1.2.3.1'
        with self.assertRaisesRegex(m.VerificationError,'sop_reused'):a.check_global_sources(self.rows(),reports)

class PermissionGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'private').mkdir();(self.root/'results').mkdir()
        candidates=['SYNTHETIC_'+str(k) for k in range(100)]
        def eligible(p):return int(hashlib.sha256(('slice-placement-v1:'+p).encode()).hexdigest()[:12],16)/float(16**12)<.70
        self.allowed=next(p for p in candidates if eligible(p));self.held=next(p for p in candidates if not eligible(p))
        self.source=self.root/'restriction_source.txt';self.source.write_text('synthetic frozen metadata')
        self.pool=self.root/'private/PRIVATE_restriction_permitted_participants.csv'
        self.pool.write_text('participant_id\n'+self.allowed+'\n')
        self.record={'locked_manifest_hash_valid':True,'output_sha256':file_sha256(self.pool),'hashes':{str(self.source):file_sha256(self.source)}}
        self.save()
    def save(self):(self.root/'results/restriction_gate.json').write_text(json.dumps(self.record))
    def tearDown(self):self.temp.cleanup()
    def test_unchanged_allowed_metadata_passes(self):require_source_permission(self.root,[{'participant_id':self.allowed}])
    def test_modified_permitted_file_fails(self):
        self.pool.write_text(self.pool.read_text()+'SYNTHETIC_EXTRA\n')
        with self.assertRaisesRegex(ValueError,'gate_integrity'):require_source_permission(self.root,[{'participant_id':self.allowed}])
    def test_changed_restriction_source_fails(self):
        self.source.write_text('changed')
        with self.assertRaisesRegex(ValueError,'source_version_changed'):require_source_permission(self.root,[{'participant_id':self.allowed}])
    def test_held_hash_rejected_even_if_in_allowed_file(self):
        self.pool.write_text('participant_id\n'+self.held+'\n');self.record['output_sha256']=file_sha256(self.pool);self.save()
        with self.assertRaisesRegex(ValueError,'permission_gate_failed'):require_source_permission(self.root,[{'participant_id':self.held}])

if __name__=='__main__':
    suite=unittest.TestSuite()
    for name in ['test_reader_schema_generated_case_and_nifti_agree','test_reader_schema_rejects_private_sampling_and_partition_fields','test_reader_schema_rejects_geometry_not_matching_image']:
        suite.addTest(ReaderSchema(name))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(SourceBinding))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PermissionGate))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
