#!/usr/bin/env python3
"""Maintained INPUT preparation route: original single-frame MR DICOM to native NIfTI.

Never reads masks, changes anatomy, resamples or normalises. A source folder must
contain exactly the selected series (all files are parsed, no extension filtering).
All source checksums and slice identities belong in --private-report, outside the
reader package. Original visit/month is an explicit archive-metadata binding;
DICOM dates are checked but are not used to invent visit mappings.

Dependencies: numpy, pydicom, SimpleITK. Run `python native_mri_package.py --help`.
Header/corner checks adapt readiness-audit check_annotation_file.py's tested
approach; source identity and exact DICOM pixel checks are additional here.
"""
import argparse
import csv
import datetime
import gzip
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import struct
import sys

import numpy as np
import pydicom
import SimpleITK as sitk
from package_layout import verify_relative_folder

VERSION = 'native_mri_package/1'
TOL = {'orientation': 1e-5, 'position_mm': 0.01, 'slice_gap_spread_mm': 0.01,
       'pixel_spacing_mm': 1e-5, 'saved_corner_mm': 0.01}

class VerificationError(ValueError):
    pass

def need(ok, code):
    if not ok:
        raise VerificationError(code)

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def corners(shape):
    return np.array(list(itertools.product(*[(0, s-1) for s in shape])), dtype=float)

def world(affine, points):
    return np.column_stack((points, np.ones(len(points)))) @ affine.T

def check_nifti(path, expected_shape=None, expected_lps_affine=None):
    """Reject absent, contradictory transforms and unknown units before loader use.

    NIfTI-1 scalar real volumes only. Both qform and sform must be active, explicit
    millimetres, mutually consistent and equal the original DICOM physical grid.
    """
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as f:
        h = f.read(352)
    need(len(h) == 352, 'nifti_short_header')
    endian = '<' if struct.unpack('<i', h[:4])[0] == 348 else '>'
    need(struct.unpack(endian+'i', h[:4])[0] == 348 and h[344:348] == b'n+1\0', 'unsupported_nifti_header')
    dims = struct.unpack_from(endian+'8h', h, 40)
    shape = dims[1:4]
    need(dims[0] == 3 and min(shape) > 0, 'nifti_requires_scalar_3d')
    need(expected_shape is None or tuple(shape) == tuple(expected_shape), 'nifti_dimensions_changed')
    need(h[123] & 7 == 2, 'nifti_spatial_units_not_mm')
    qcode, scode = struct.unpack_from(endian+'2h', h, 252)
    need(qcode > 0 and scode > 0, 'nifti_requires_active_qform_sform')
    pix = struct.unpack_from(endian+'8f', h, 76)
    need(np.isfinite(pix).all() and min(pix[1:4]) > 0, 'nifti_invalid_spacing')
    b,c,d,x,y,z = struct.unpack_from(endian+'6f', h, 256)
    need(np.isfinite([b,c,d,x,y,z]).all(), 'nifti_nonfinite_qform')
    norm = b*b+c*c+d*d
    # NIfTI convention for a 180-degree rotation: small float roundoff may push
    # the sum just above one. Larger errors are invalid.
    need(norm <= 1+1e-5, 'nifti_invalid_quaternion')
    if norm > 1:
        b,c,d = np.asarray([b,c,d])/math.sqrt(norm)
    a = math.sqrt(max(0, 1-b*b-c*c-d*d))
    rotation = np.array([[a*a+b*b-c*c-d*d,2*(b*c-a*d),2*(b*d+a*c)],
                         [2*(b*c+a*d),a*a+c*c-b*b-d*d,2*(c*d-a*b)],
                         [2*(b*d-a*c),2*(c*d+a*b),a*a+d*d-b*b-c*c]])
    q = np.eye(4)
    q[:3,:3] = rotation @ np.diag([pix[1], pix[2], pix[3]*(-1 if pix[0] < 0 else 1)])
    q[:3,3] = [x,y,z]
    s = np.vstack([np.asarray(struct.unpack_from(endian+'12f', h, 280)).reshape(3,4), [0,0,0,1]])
    need(np.isfinite(s).all() and abs(np.linalg.det(s[:3,:3])) > 1e-12, 'nifti_invalid_sform')
    p = corners(shape)
    qs_error = float(np.linalg.norm((world(q,p)-world(s,p))[:,:3], axis=1).max())
    need(qs_error <= TOL['saved_corner_mm'], 'nifti_contradictory_transforms')
    source_error = None
    if expected_lps_affine is not None:
        ras_to_lps = np.diag([-1,-1,1,1])
        target = world(expected_lps_affine,p)
        source_error = max(float(np.linalg.norm((world(ras_to_lps @ a_,p)-target)[:,:3], axis=1).max()) for a_ in (q,s))
        need(source_error <= TOL['saved_corner_mm'], 'nifti_transform_differs_from_source')
    return {'qform_code': qcode, 'sform_code': scode, 'spatial_units': 'mm',
            'qform_sform_max_corner_error_mm': qs_error, 'source_max_corner_error_mm': source_error}

def validate_selection(rows, required_count=None):
    """A global source key/UID may never map to conflicting identities or be reused."""
    need(required_count is None or len(rows) == required_count, 'selection_count_mismatch')
    participants, cases, sources, uids = set(), set(), {}, {}
    for row in rows:
        ident = (str(row['participant_id']), int(row['visit_month']), row['knee_side'])
        need(ident[2] in ('L','R') and ident[1] >= 0, 'invalid_case_identity')
        need(ident[0] not in participants, 'participant_selected_twice')
        participants.add(ident[0])
        need(row['case_key'] not in cases, 'duplicate_case_key')
        cases.add(row['case_key'])
        for key, record in ((row['source_series_key'], sources), (row.get('series_instance_uid'), uids)):
            if not key:
                continue
            need(key not in record or record[key] == ident, 'source_key_conflicting_identity')
            need(key not in record, 'duplicate_source_series')
            record[key] = ident
    return True

def normalize_side(value):
    return {'R':'R','RIGHT':'R','L':'L','LEFT':'L'}.get(str(value).strip().upper())

def dicom_side(ds):
    sides = set()
    for field in ('ImageLaterality','Laterality'):
        value = str(getattr(ds, field, '')).strip()
        if value:
            side = normalize_side(value)
            need(side is not None, 'unsupported_dicom_laterality')
            sides.add(side)
    desc = str(getattr(ds, 'SeriesDescription', '')).upper()
    for word, side in (('RIGHT','R'),('LEFT','L')):
        if re.search(r'(^|[^A-Z])'+word+r'($|[^A-Z])', desc):
            sides.add(side)
    need(len(sides) == 1, 'missing_or_conflicting_dicom_side')
    return sides.pop()

def load_source(folder, row):
    """Read every required file; return physically ordered float64-scaled pixels."""
    files = sorted(p for p in Path(folder).rglob('*') if p.is_file())
    need(len(files) == int(row['expected_slice_count']), 'source_file_count_mismatch')
    need(len(files) >= 2, 'source_too_few_slices')
    required = ['participant_id','visit_month','original_visit_code','study_date','archive_series_number',
                'series_description_recorded','source_series_key','case_key','dataset_version','source_visit_label']
    need(all(str(row.get(k, '')).strip() for k in required), 'selection_missing_source_binding')
    expected_side = row['knee_side']
    records, datasets, sop_uids = [], [], set()
    consistent = None
    for path in files:
        before = sha256(path)
        try:
            ds = pydicom.dcmread(str(path))
        except Exception as exc:
            raise VerificationError('source_unreadable_dicom') from exc
        need(str(getattr(ds,'Modality','')) == 'MR', 'source_not_mr')
        need(int(getattr(ds,'NumberOfFrames',1)) == 1, 'multiframe_not_supported')
        need(str(getattr(ds,'PatientID','')).strip() == str(row['participant_id']), 'source_participant_mismatch')
        need(str(getattr(ds,'StudyDate','')).strip() == str(row['study_date']), 'source_study_date_mismatch')
        if row.get('dicom_series_number') is not None:
            need(str(getattr(ds,'SeriesNumber','')).strip() == str(row['dicom_series_number']), 'source_series_number_mismatch')
        need(str(getattr(ds,'SeriesDescription','')).strip() == str(row['series_description_recorded']), 'source_description_mismatch')
        desc = str(ds.SeriesDescription).upper()
        need('SAG_IW' in desc and 'TSE' in desc, 'source_not_target_sequence')
        need(dicom_side(ds) == expected_side, 'source_side_mismatch')
        need(str(getattr(ds,'ScanningSequence','')) == 'SE', 'source_not_spin_echo')
        opts = str(getattr(ds,'ScanOptions',''))
        need('FS' in opts, 'source_fat_suppression_not_recorded')
        need(int(getattr(ds,'SamplesPerPixel',0)) == 1 and str(getattr(ds,'PhotometricInterpretation','')) == 'MONOCHROME2', 'source_not_scalar_mono2')
        need(not hasattr(ds,'ModalityLUTSequence') and not hasattr(ds,'RealWorldValueMappingSequence'), 'unsupported_intensity_mapping')
        sop = str(getattr(ds,'SOPInstanceUID',''))
        need(sop and sop not in sop_uids, 'duplicate_sop_instance')
        sop_uids.add(sop)
        uid = str(getattr(ds,'SeriesInstanceUID',''))
        study = str(getattr(ds,'StudyInstanceUID',''))
        frame = str(getattr(ds,'FrameOfReferenceUID',''))
        need(uid and study and frame, 'missing_source_uids')
        if row.get('series_instance_uid'):
            need(uid == row['series_instance_uid'], 'source_series_uid_mismatch')
        if row.get('study_instance_uid'):
            need(study == row['study_instance_uid'], 'source_study_uid_mismatch')
        signature = (uid, study, frame, int(ds.Rows), int(ds.Columns), int(ds.BitsAllocated),
                     int(ds.BitsStored), int(ds.PixelRepresentation), str(ds.PhotometricInterpretation))
        if consistent is None:
            consistent = signature
        need(signature == consistent, 'mixed_source_series_or_storage')
        for field, actual in (('native_columns_recorded',int(ds.Columns)),('native_rows_recorded',int(ds.Rows))):
            if row.get(field):
                need(actual == int(row[field]), 'source_dimensions_differ_from_inventory')
        iop = np.asarray(ds.ImageOrientationPatient, dtype=float)
        ipp = np.asarray(ds.ImagePositionPatient, dtype=float)
        pixel = np.asarray(ds.PixelSpacing, dtype=float)
        need(iop.shape == (6,) and ipp.shape == (3,) and pixel.shape == (2,), 'invalid_dicom_geometry')
        need(np.isfinite(iop).all() and np.isfinite(ipp).all() and np.isfinite(pixel).all() and (pixel > 0).all(), 'nonfinite_dicom_geometry')
        for field, actual in (('spacing_x_recorded_mm',pixel[1]),('spacing_y_recorded_mm',pixel[0])):
            if row.get(field):
                need(abs(actual-float(row[field])) <= TOL['pixel_spacing_mm'], 'source_pixel_spacing_differs_from_inventory')
        need(np.allclose(np.asarray([np.linalg.norm(iop[:3]),np.linalg.norm(iop[3:]),np.dot(iop[:3],iop[3:])]), [1,1,0], atol=TOL['orientation'], rtol=0), 'nonorthonormal_dicom_orientation')
        try:
            raw = ds.pixel_array
        except Exception as exc:
            raise VerificationError('source_pixels_unreadable') from exc
        need(raw.shape == (int(ds.Rows),int(ds.Columns)), 'source_pixel_dimensions')
        slope, intercept = float(getattr(ds,'RescaleSlope',1)), float(getattr(ds,'RescaleIntercept',0))
        need(np.isfinite([slope,intercept]).all() and slope != 0, 'invalid_dicom_scaling')
        values = raw.astype(np.float64)*slope+intercept
        need(np.isfinite(values).all(), 'nonfinite_source_values')
        need(sha256(path) == before, 'source_changed_during_read')
        records.append({'path': str(path.resolve()), 'sha256': before, 'sop_instance_uid': sop,
                        'instance_number': str(getattr(ds,'InstanceNumber','')), 'position_lps_mm': ipp.tolist(),
                        'orientation_lps': iop.tolist(), 'pixel_spacing_row_column_mm':pixel.tolist(),
                        'rescale_slope':slope,'rescale_intercept':intercept})
        datasets.append((iop,ipp,pixel,values))
    iop0,_,pixel0,_ = datasets[0]
    x = iop0[:3]/np.linalg.norm(iop0[:3]); y = iop0[3:]/np.linalg.norm(iop0[3:])
    normal = np.cross(x,y); normal /= np.linalg.norm(normal)
    need(abs(normal[0]) >= math.cos(math.radians(45)), 'source_not_sagittal')
    for iop,_,pixel,_ in datasets:
        need(np.allclose(iop,iop0,rtol=0,atol=TOL['orientation']), 'inconsistent_slice_orientation')
        need(np.allclose(pixel,pixel0,rtol=0,atol=TOL['pixel_spacing_mm']), 'inconsistent_pixel_spacing')
    order = np.argsort([np.dot(v[1],normal) for v in datasets])
    datasets = [datasets[i] for i in order]; records = [records[i] for i in order]
    positions = np.array([v[1] for v in datasets])
    along = positions @ normal
    gaps = np.diff(along)
    need((gaps > TOL['position_mm']).all(), 'duplicate_or_overlapping_slice_positions')
    need(float(np.ptp(gaps)) <= TOL['slice_gap_spread_mm'], 'materially_irregular_slice_spacing')
    step = float((along[-1]-along[0])/(len(along)-1))
    predicted = positions[0]+np.arange(len(positions))[:,None]*step*normal
    residual = float(np.linalg.norm(predicted-positions,axis=1).max())
    need(residual <= TOL['position_mm'], 'slice_origins_not_on_regular_orthogonal_grid')
    if row.get('slice_step_recorded_mm'):
        need(abs(step-float(row['slice_step_recorded_mm'])) <= TOL['slice_gap_spread_mm'], 'source_slice_spacing_differs_from_inventory')
    for item in datasets:
        need(item[3].shape == datasets[0][3].shape, 'inconsistent_pixel_dimensions')
    array = np.stack([v[3] for v in datasets])
    affine = np.eye(4)
    affine[:3,:3] = np.column_stack([x*pixel0[1], y*pixel0[0], normal*step])
    affine[:3,3] = positions[0]
    return array, affine, {'source_files':records, 'series_instance_uid':consistent[0],
                          'study_instance_uid':consistent[1], 'frame_of_reference_uid':consistent[2],
                          'slice_gap_min_mm':float(gaps.min()), 'slice_gap_max_mm':float(gaps.max()),
                          'regular_grid_max_residual_mm':residual,
                          'dicom_series_number':str(getattr(ds,'SeriesNumber','')),
                          'intensity_mapping':'stored pixels × per-slice RescaleSlope + RescaleIntercept; no normalisation'}

def verify_volume(path, array, affine, source=None):
    shape = tuple(array.shape[::-1])
    header = check_nifti(path, shape, affine)
    saved = sitk.ReadImage(str(path))
    values = sitk.GetArrayFromImage(saved)
    need(values.shape == array.shape and np.array_equal(values,array), 'saved_voxels_differ_from_scaled_dicom')
    need(np.isfinite(values).all(), 'saved_nonfinite_values')
    loaded = np.eye(4)
    loaded[:3,:3] = np.asarray(saved.GetDirection()).reshape(3,3) @ np.diag(saved.GetSpacing())
    loaded[:3,3] = saved.GetOrigin()
    err = float(np.linalg.norm((world(loaded,corners(shape))-world(affine,corners(shape)))[:,:3],axis=1).max())
    need(err <= TOL['saved_corner_mm'], 'reopened_world_coordinates_differ')
    # Compare every slice's four corner voxel centres, rather than headers alone.
    points = np.array([(x,y,k) for k in range(shape[2]) for x in (0,shape[0]-1) for y in (0,shape[1]-1)],dtype=float)
    err_all = float(np.linalg.norm((world(loaded,points)-world(affine,points))[:,:3],axis=1).max())
    need(err_all <= TOL['saved_corner_mm'], 'reopened_slice_coordinates_differ')
    direct_error = None
    if source is not None:
        acquired = []
        for record in source['source_files']:
            pos = np.asarray(record['position_lps_mm'])
            iop = np.asarray(record['orientation_lps'])
            ps = np.asarray(record['pixel_spacing_row_column_mm'])
            acquired.extend(pos + x*iop[:3]*ps[1]+y*iop[3:]*ps[0] for x in (0,shape[0]-1) for y in (0,shape[1]-1))
        direct_error = float(np.linalg.norm(world(loaded,points)[:,:3]-np.asarray(acquired),axis=1).max())
        need(direct_error <= TOL['saved_corner_mm'], 'reopened_coordinates_differ_from_original_dicom')
    return dict(header, original_dicom_all_slice_corner_error_mm=direct_error, reopened_max_corner_error_mm=err, all_slice_corner_error_mm=err_all,
                all_voxels_match_scaled_original_dicom=True, saved_dtype=str(values.dtype),
                image_sha256=sha256(path))

def export_case(folder, row, output_dir, private_report):
    out = Path(output_dir); report_path = Path(private_report)
    need(not out.exists(), 'output_folder_already_exists')
    need(not report_path.exists(), 'private_report_already_exists')
    need(out.resolve() not in report_path.resolve().parents, 'private_report_inside_reader_case')
    array,affine,source = load_source(folder,row)
    out.mkdir(parents=True)
    try:
        im = sitk.GetImageFromArray(array)
        spacing = np.linalg.norm(affine[:3,:3],axis=0)
        im.SetSpacing(tuple(spacing)); im.SetOrigin(tuple(affine[:3,3]))
        im.SetDirection(tuple((affine[:3,:3]/spacing).ravel()))
        image_path = out/'image.nii.gz'
        sitk.WriteImage(im,str(image_path),True)
        checked = verify_volume(image_path,array,affine,source)
        case = {'schema_version':'meniscus_case/1','dataset_version':row['dataset_version'],
                'case_key':row['case_key'],'participant_id':str(row['participant_id']),
                'visit_month':int(row['visit_month']),'original_visit_code':row['original_visit_code'],
                'source_visit_label':row['source_visit_label'],
                'knee_side':row['knee_side'],'sequence':'sagittal IW fat-suppressed TSE',
                'source_series_key':row['source_series_key'],'series_instance_uid':source['series_instance_uid'],
                'archive_series_number':str(row['archive_series_number']),
                'dicom_series_number':source['dicom_series_number'], 'source_study_date':row['study_date'],
                'source_series_description':row['series_description_recorded'],
                'dimensions_xyz':list(array.shape[::-1]),'spacing_xyz_mm':spacing.tolist(),
                'origin_lps_mm':affine[:3,3].tolist(),'direction_lps_columns':(affine[:3,:3]/spacing).tolist(),
                'expected_slice_count':int(row['expected_slice_count']),
                'slice_index_convention':'zero-based along physical volume axis 2; ascending projection on DICOM row-direction cross column-direction; never InstanceNumber',
                'image_sha256':checked['image_sha256'],'annotation_status':'not_started',
                'preparation_verifier':VERSION}
        (out/'case.json').write_text(json.dumps(case,indent=2)+'\n')
        with (out/'slice_review.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['slice_index','status']);w.writeheader()
            w.writerows({'slice_index':k,'status':'not_reviewed'} for k in range(array.shape[0]))
        # Layout revision 2 keeps source case folders to the three immutable files.
        # A historical nested batch may retain its known empty placeholder.
        if row.get('relative_folder') and verify_relative_folder(row['relative_folder'],row)=='legacy':
            (out/'annotations').mkdir()
        report = {'schema_version':VERSION,'passed':True,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'selection':row,'source':source,'saved_volume':checked,
                  'source_identity_fingerprint':canonical_hash({'participant_id':row['participant_id'],'visit_month':row['visit_month'],
                      'knee_side':row['knee_side'],'source_series_key':row['source_series_key'],'series_instance_uid':source['series_instance_uid']}),
                  'tolerances':TOL,'software':{'numpy':np.__version__,'pydicom':pydicom.__version__,'SimpleITK':sitk.Version_VersionString()},
                  'limits':'Input identity/grid/intensity verification only. Does not establish segmentation accuracy, completeness of annotation, or historical test independence.'}
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2)+'\n'); report_path.chmod(0o600)
        return report
    except Exception:
        # Preserve evidence of partial work; caller must inspect before resume.
        (out/'PREPARATION_FAILED.txt').write_text('Incomplete preparation. Do not copy this case into the final package. Inspect private job log.\n')
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--series-dir',required=True);p.add_argument('--selection-json',required=True)
    p.add_argument('--output-dir',required=True);p.add_argument('--private-report',required=True)
    args=p.parse_args()
    try:
        report=export_case(args.series_dir,json.loads(Path(args.selection_json).read_text()),args.output_dir,args.private_report)
        print(json.dumps({'passed':report['passed'],'slice_count':len(report['source']['source_files'])}))
    except Exception as exc:
        # No path or participant identifiers on stdout/stderr.
        code = str(exc) if isinstance(exc, VerificationError) else type(exc).__name__
        print(json.dumps({'passed':False,'error':code}),file=sys.stderr);return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
