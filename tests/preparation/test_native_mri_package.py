"""Technical tests on generated nonparticipant DICOM, never anatomical validation."""
import csv
import gzip
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
import SimpleITK as sitk

import native_mri_package as m

class NativeInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root/'source'; self.src.mkdir()
        self.row = dict(participant_id='SYNTHETIC',visit_month=0,original_visit_code='0.E.1',source_visit_label='v00',
            study_date='20000101',archive_series_number='ARCHIVEKEY',series_description_recorded='SAG_IW_TSE_RIGHT',
            knee_side='R',expected_slice_count=7,source_series_key='synthetic-source',case_key='synthetic-case',
            dataset_version='synthetic/1',dicom_series_number='6')
        angle = np.deg2rad(23)
        x=np.array([np.sin(angle),np.cos(angle),0]); y=np.array([0,0,-1]); z=np.cross(x,y)
        self.iop=np.r_[x,y]; self.origin=np.array([-40,30,60.])
        self.uid=generate_uid(); study=generate_uid(); frame=generate_uid()
        self.truth=np.empty((7,8,9),np.float64)
        for k in range(7):
            meta=FileMetaDataset(); meta.TransferSyntaxUID=ExplicitVRLittleEndian
            meta.MediaStorageSOPClassUID=MRImageStorage;meta.MediaStorageSOPInstanceUID=generate_uid()
            ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
            ds.is_little_endian=True;ds.is_implicit_VR=False
            ds.SOPClassUID=MRImageStorage;ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
            ds.PatientID='SYNTHETIC';ds.StudyDate='20000101';ds.Modality='MR'
            ds.SeriesInstanceUID=self.uid;ds.StudyInstanceUID=study;ds.FrameOfReferenceUID=frame
            ds.SeriesNumber=6;ds.InstanceNumber=7-k;ds.SeriesDescription='SAG_IW_TSE_RIGHT'
            ds.ScanningSequence='SE';ds.ScanOptions=['SAT2','FS'];ds.ImageLaterality='R'
            ds.ImageOrientationPatient=self.iop.tolist();ds.ImagePositionPatient=(self.origin+3*k*z).tolist()
            ds.PixelSpacing=[0.37,0.35];ds.Rows=8;ds.Columns=9
            ds.SamplesPerPixel=1;ds.PhotometricInterpretation='MONOCHROME2'
            ds.BitsAllocated=16;ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
            raw=np.arange(72,dtype=np.uint16).reshape(8,9)+100*k
            # Slice-specific scaling ensures ordering/scaling checked together.
            ds.RescaleSlope=1.5+k/8;ds.RescaleIntercept=-20.25
            ds.PixelData=raw.tobytes();self.truth[k]=raw*float(ds.RescaleSlope)+float(ds.RescaleIntercept)
            # Deliberately reverse filename and instance ordering.
            ds.save_as(self.src/('IM%03d.dcm'%(7-k)),write_like_original=False)
    def tearDown(self):self.tmp.cleanup()
    def mutate(self,k,fn):
        p=sorted(self.src.iterdir())[k];ds=pydicom.dcmread(p);fn(ds);ds.save_as(p,write_like_original=False)
    def reject(self,code):
        with self.assertRaisesRegex(m.VerificationError,code):m.load_source(self.src,self.row)
    def export(self):return m.export_case(self.src,self.row,self.root/'case',self.root/'private'/'report.json')
    def test_oblique_reverse_order_scaling_all_pixels_and_corners(self):
        report=self.export(); case=json.loads((self.root/'case'/'case.json').read_text())
        got=sitk.GetArrayFromImage(sitk.ReadImage(str(self.root/'case'/'image.nii.gz')))
        np.testing.assert_array_equal(got,self.truth)
        self.assertTrue(report['saved_volume']['all_voxels_match_scaled_original_dicom'])
        self.assertLess(report['saved_volume']['original_dicom_all_slice_corner_error_mm'],.01)
        self.assertEqual(case['dimensions_xyz'],[9,8,7]);self.assertEqual(case['annotation_status'],'not_started')
        self.assertFalse((self.root/'case'/'annotations').exists())
        with (self.root/'case'/'slice_review.csv').open() as stream:rows=list(csv.DictReader(stream))
        self.assertEqual([int(r['slice_index']) for r in rows],list(range(7)))
        self.assertEqual({r['status'] for r in rows},{'not_reviewed'})
        self.assertEqual(report['source']['source_files'][0]['instance_number'],'7')
        self.assertEqual(case['archive_series_number'],'ARCHIVEKEY')
        self.assertEqual(case['dicom_series_number'],'6')
    def test_missing_slice_fails_expected_count(self):
        next(self.src.iterdir()).unlink();self.reject('source_file_count_mismatch')
    def test_missing_middle_even_with_changed_expected_count_fails_spacing(self):
        (self.src/'IM004.dcm').unlink();self.row['expected_slice_count']=6;self.reject('materially_irregular_slice_spacing')
    def test_extra_non_dicom_file_fails(self):
        (self.src/'README').write_text('unexpected');self.reject('source_file_count_mismatch')
    def test_unreadable_dicom_fails(self):
        (self.src/'IM004.dcm').write_text('bad');self.reject('source_unreadable_dicom')
    def test_duplicate_sop_fails(self):
        uid=str(pydicom.dcmread(sorted(self.src.iterdir())[0]).SOPInstanceUID)
        self.mutate(1,lambda d:setattr(d,'SOPInstanceUID',uid));self.reject('duplicate_sop_instance')
    def test_duplicate_position_fails(self):
        pos=pydicom.dcmread(sorted(self.src.iterdir())[0]).ImagePositionPatient
        self.mutate(1,lambda d:setattr(d,'ImagePositionPatient',pos));self.reject('duplicate_or_overlapping_slice_positions')
    def test_inconsistent_orientation_fails(self):
        def change(d):
            a=np.deg2rad(24);d.ImageOrientationPatient=[float(np.sin(a)),float(np.cos(a)),0,0,0,-1]
        self.mutate(1,change);self.reject('inconsistent_slice_orientation')
    def test_inplane_shift_fails_without_repair(self):
        def change(d):d.ImagePositionPatient=list(np.asarray(d.ImagePositionPatient)+self.iop[:3]*.1)
        self.mutate(2,change);self.reject('slice_origins_not_on_regular_orthogonal_grid')
    def test_irregular_spacing_fails(self):
        def change(d):d.ImagePositionPatient=list(np.asarray(d.ImagePositionPatient)+np.cross(self.iop[:3],self.iop[3:])*.1)
        self.mutate(2,change);self.reject('materially_irregular_slice_spacing')
    def test_mixed_series_fails(self):
        self.mutate(1,lambda d:setattr(d,'SeriesInstanceUID',generate_uid()));self.reject('mixed_source_series')
    def test_wrong_participant_fails(self):
        self.mutate(1,lambda d:setattr(d,'PatientID','OTHER'));self.reject('source_participant_mismatch')
    def test_wrong_side_fails(self):
        self.mutate(1,lambda d:setattr(d,'ImageLaterality','L'));self.reject('missing_or_conflicting_dicom_side')
    def test_wrong_date_fails(self):
        self.mutate(1,lambda d:setattr(d,'StudyDate','20000102'));self.reject('source_study_date_mismatch')
    def test_wrong_sequence_fails(self):
        self.row['series_description_recorded']='SAG_DESS_RIGHT'
        for k in range(7):self.mutate(k,lambda d:setattr(d,'SeriesDescription','SAG_DESS_RIGHT'))
        self.reject('source_not_target_sequence')
    def test_missing_fat_suppression_fails(self):
        self.mutate(1,lambda d:setattr(d,'ScanOptions','SAT2'));self.reject('source_fat_suppression_not_recorded')
    def test_wrong_expected_uid_fails(self):
        self.row['series_instance_uid']=generate_uid();self.reject('source_series_uid_mismatch')
    def test_source_dimensions_inventory_mismatch_fails(self):
        self.row['native_columns_recorded']='448';self.reject('source_dimensions_differ_from_inventory')
    def test_source_spacing_inventory_mismatch_fails(self):
        self.row['spacing_x_recorded_mm']='0.5';self.reject('source_pixel_spacing_differs_from_inventory')
    def test_source_slice_spacing_inventory_mismatch_fails(self):
        self.row['slice_step_recorded_mm']='2.5';self.reject('source_slice_spacing_differs_from_inventory')
    def test_historical_nested_export_keeps_only_empty_legacy_placeholder(self):
        from package_layout import canonical_relative_folder
        self.row['relative_folder']=canonical_relative_folder(self.row,'legacy')
        self.export()
        self.assertEqual(list((self.root/'case'/'annotations').iterdir()),[])
        self.assertEqual(set(p.name for p in (self.root/'case').iterdir()),{'image.nii.gz','case.json','slice_review.csv','annotations'})
    def test_fractional_scaling_saved_exactly(self):
        report=self.export();self.assertEqual(report['saved_volume']['saved_dtype'],'float64')
    def edit_header(self,offset,payload):
        path=self.root/'case'/'image.nii.gz'
        with gzip.open(path,'rb') as f:data=bytearray(f.read())
        data[offset:offset+len(payload)]=payload
        with gzip.open(path,'wb') as f:f.write(data)
        return path
    def test_unknown_units_fails(self):
        self.export();path=self.edit_header(123,b'\0')
        with self.assertRaisesRegex(m.VerificationError,'spatial_units'):m.check_nifti(path)
    def test_contradictory_transforms_fails(self):
        self.export();path=self.root/'case'/'image.nii.gz'
        with gzip.open(path,'rb') as f:h=f.read(352)
        value=struct.unpack_from('<f',h,292)[0]
        path=self.edit_header(292,struct.pack('<f',value+1))
        with self.assertRaisesRegex(m.VerificationError,'contradictory'):m.check_nifti(path)
    def test_no_qform_fails(self):
        self.export();path=self.edit_header(252,struct.pack('<h',0))
        with self.assertRaisesRegex(m.VerificationError,'active_qform'):m.check_nifti(path)
    def test_reopened_changed_pixels_fails(self):
        self.export();array,affine,source=m.load_source(self.src,self.row)
        path=self.root/'case'/'image.nii.gz';im=sitk.ReadImage(str(path))
        values=sitk.GetArrayFromImage(im);values[1,2,3]+=1
        changed=sitk.GetImageFromArray(values);changed.CopyInformation(im);sitk.WriteImage(changed,str(path))
        with self.assertRaisesRegex(m.VerificationError,'saved_voxels'):m.verify_volume(path,array,affine,source)
    def test_output_overwrite_refused(self):
        self.export()
        with self.assertRaisesRegex(m.VerificationError,'already_exists'):self.export()
    def test_private_record_cannot_enter_reader_case(self):
        with self.assertRaisesRegex(m.VerificationError,'inside_reader_case'):
            m.export_case(self.src,self.row,self.root/'case',self.root/'case'/'private.json')

class Manifest(unittest.TestCase):
    def row(self,**kw):
        r=dict(participant_id='SYNTHETIC1',visit_month=0,knee_side='R',case_key='one',source_series_key='key1');r.update(kw);return r
    def test_source_key_conflicting_identity_fails(self):
        with self.assertRaisesRegex(m.VerificationError,'source_key_conflicting_identity'):
            m.validate_selection([self.row(),self.row(participant_id='SYNTHETIC2',case_key='two')])
    def test_uid_conflicting_identity_fails(self):
        with self.assertRaisesRegex(m.VerificationError,'source_key_conflicting_identity'):
            m.validate_selection([self.row(series_instance_uid='uid'),self.row(participant_id='SYNTHETIC2',case_key='two',source_series_key='key2',series_instance_uid='uid')])
    def test_participant_unique_across_visits_and_sides(self):
        with self.assertRaisesRegex(m.VerificationError,'participant_selected_twice'):
            m.validate_selection([self.row(),self.row(visit_month=96,knee_side='L',case_key='two',source_series_key='key2')])
    def test_correct_unique_manifest(self):
        self.assertTrue(m.validate_selection([self.row(),self.row(participant_id='SYNTHETIC2',case_key='two',source_series_key='key2')],2))

if __name__=='__main__':unittest.main(verbosity=2)
