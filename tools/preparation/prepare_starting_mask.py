"""Prepare an existing pipeline prediction for correction on its acquired MRI grid.

This is not inference or anatomical correction. For the binary whole-OAI release,
the recorded existing Stage-C sagittal-plane split is reproduced and verified in
LPS coordinates. Every source foreground voxel receives the original pipeline's
medial/lateral assignment. A missing split is unresolved, never an empty mask.
Categorical resampling is nearest-neighbour with an identity physical transform.

All detailed context/source paths belong in the private report. Source MRI and
prediction files are read only and their bytes must remain unchanged.
"""
import argparse
import copy
import datetime
import gzip
import json
import math
import os
from pathlib import Path
import struct
import uuid

import numpy as np
import SimpleITK as sitk

from native_mri_package import check_nifti, corners, sha256, world

VERSION = 'prepare_starting_mask/1'
LABELS = {'0': 'no predicted meniscus', '1': 'medial meniscus', '2': 'lateral meniscus'}
GRID_TOL_MM = 0.01
NN_TIE_TOL = 1e-7


class StartingMaskError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise StartingMaskError(code)


def affine_lps(image):
    affine = np.eye(4)
    affine[:3, :3] = np.asarray(image.GetDirection()).reshape(3, 3) @ np.diag(image.GetSpacing())
    affine[:3, 3] = image.GetOrigin()
    return affine


def grid(image):
    return {'dimensions_xyz': list(image.GetSize()), 'spacing_xyz_mm': list(image.GetSpacing()),
            'origin_lps_mm': list(image.GetOrigin()),
            'direction_lps_columns': np.asarray(image.GetDirection()).reshape(3, 3).tolist()}


def read_reference(path):
    """Load source MRI geometry without decoding or modifying its intensities."""
    check_nifti(path)
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    need(reader.GetDimension() == 3 and reader.GetNumberOfComponents() == 1, 'MRI_not_scalar_3d')
    reference = sitk.Image(reader.GetSize(), sitk.sitkUInt8)
    reference.SetSpacing(reader.GetSpacing())
    reference.SetOrigin(reader.GetOrigin())
    reference.SetDirection(reader.GetDirection())
    return reference


def raw_mask_storage(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        header = stream.read(352)
    endian = '<' if struct.unpack('<i', header[:4])[0] == 348 else '>'
    datatype = struct.unpack_from(endian + 'h', header, 70)[0]
    slope, intercept = struct.unpack_from(endian + '2f', header, 112)
    need(datatype in (2, 4, 8, 256, 512, 768, 1024, 1280), 'prediction_storage_not_integer')
    need((slope == 0 or slope == 1) and (slope == 0 or intercept == 0), 'prediction_has_intensity_scaling')


def boolean(value):
    if type(value) is bool:
        return value
    if value in (0, '0', 'False', 'false'):
        return False
    if value in (1, '1', 'True', 'true'):
        return True
    raise StartingMaskError('invalid_recorded_boolean')


def integer(value):
    need(type(value) is not bool, 'invalid_recorded_integer')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise StartingMaskError('missing_existing_pipeline_split')
    need(math.isfinite(number) and number.is_integer(), 'invalid_recorded_integer')
    return int(number)


def label_existing_binary(array, source_affine, side, split):
    """Reproduce existing Stage-C regions; no cut is estimated in this function."""
    need(np.issubdtype(array.dtype, np.integer) and np.isin(array, [0, 1]).all(), 'source_not_binary_release')
    need(array.any(), 'empty_source_prediction_unresolved')
    need(side in ('L', 'R'), 'invalid_case_side')
    need(isinstance(split, dict) and split, 'missing_existing_pipeline_split')
    if 'split' in split:
        need(boolean(split['split']), 'source_has_no_existing_anatomical_split')
    cut = integer(split.get('split_cut_plane'))
    need(0 < cut < array.shape[0], 'invalid_existing_pipeline_cut')
    medial_low = boolean(split.get('medial_is_low_index'))
    need(split.get('split_method') in ('april', 'valley'), 'unsupported_existing_split_method')
    source = array.astype(bool)
    low = np.argwhere(source[:cut])
    high = np.argwhere(source[cut:])
    need(len(low) > 0 and len(high) > 0, 'existing_split_has_empty_compartment')
    high[:, 0] += cut
    # Pipeline centroid_x: mean KJI indices -> physical LPS x via source grid.
    x_low = float((source_affine @ np.r_[low.mean(axis=0)[::-1], 1.])[0])
    x_high = float((source_affine @ np.r_[high.mean(axis=0)[::-1], 1.])[0])
    need(abs(x_low - x_high) > 1e-5, 'compartment_centroids_not_separated')
    try:
        recorded_low, recorded_high = float(split['x_low_index_mm']), float(split['x_high_index_mm'])
    except (ValueError, TypeError, KeyError):
        raise StartingMaskError('missing_recorded_compartment_centroids')
    need(np.isfinite([recorded_low, recorded_high]).all() and max(abs(x_low - recorded_low), abs(x_high - recorded_high)) <= GRID_TOL_MM,
         'source_compartment_centroids_disagree_with_pipeline')
    expected_medial_low = (x_low > x_high) if side == 'R' else (x_low < x_high)
    need(medial_low == expected_medial_low, 'recorded_medial_assignment_disagrees_with_LPS_anatomical_side')
    labels = np.zeros(array.shape, dtype=np.uint8)
    labels[:cut] = np.where(source[:cut], 1 if medial_low else 2, 0)
    labels[cut:] = np.where(source[cut:], 2 if medial_low else 1, 0)
    need(np.array_equal(labels > 0, source), 'binary_prediction_not_preserved_by_label_assignment')
    return labels, {'method': 'existing_regen_stage_c_regions_V20', 'source_array_axis': 'K (NumPy axis 0; NIfTI axis 2)',
                    'first_high_index_plane': cut, 'split_method': split['split_method'],
                    'medial_is_low_index': medial_low, 'actual_x_low_lps_mm': x_low,
                    'actual_x_high_lps_mm': x_high,
                    'anatomical_rule': 'R: larger LPS x is medial; L: smaller LPS x is medial',
                    'source_total_foreground_voxels': int(source.sum()),
                    'source_total_prediction_preserved_before_resampling': True}


def image_from_source_labels(labels, source):
    """Label assignment changes categories on the ORIGINAL source array/grid only."""
    result = sitk.GetImageFromArray(labels)
    result.SetSpacing(source.GetSpacing())
    result.SetOrigin(source.GetOrigin())
    result.SetDirection(source.GetDirection())
    return result


def physical_nearest(source_labels, source_affine, target_affine, target_shape_xyz, actual=None):
    """Independent vectorized target-centre -> source-index nearest-neighbour check.

    Machine-precision half-voxel ties may select either equally near category. No
    allowance is made away from an explicitly counted 1e-7-voxel tie boundary.
    """
    size = np.asarray(source_labels.shape[::-1])
    need(np.isfinite(source_affine).all() and np.isfinite(target_affine).all(), 'physical_mapping_nonfinite')
    mapping = np.einsum('ij,jk->ik', np.linalg.inv(source_affine), target_affine, optimize=False)
    need(np.isfinite(mapping).all(), 'physical_mapping_nonfinite')
    nx, ny, nz = target_shape_xyz
    x, y = np.meshgrid(np.arange(nx), np.arange(ny), indexing='xy')
    plane = np.vstack((x.ravel(), y.ravel(), np.zeros(nx * ny), np.ones(nx * ny)))
    expected = np.zeros((nz, ny, nx), dtype=np.uint8)
    outside, ties, tie_label_alternatives = 0, 0, 0
    for k in range(nz):
        plane[2] = k
        # Avoid a BLAS kernel here: some NumPy/macOS BLAS combinations report
        # spurious floating-point flags for the long, thin matrix product.
        continuous = np.einsum('ij,jk->ik', mapping[:3], plane, optimize=False)
        need(np.isfinite(continuous).all(), 'target_to_source_coordinates_nonfinite')
        nearest = np.floor(continuous + .5).astype(np.int64)
        valid = ((nearest >= 0) & (nearest < size[:, None])).all(axis=0)
        outside += int((~valid).sum())
        flat = expected[k].ravel()
        flat[valid] = source_labels[nearest[2, valid], nearest[1, valid], nearest[0, valid]]
        fractions = continuous - np.floor(continuous)
        tie = (np.abs(fractions - .5) <= NN_TIE_TOL)
        ties += int(tie.any(axis=0).sum())
        if actual is not None:
            actual_flat = actual[k].ravel()
            bad = np.flatnonzero(flat != actual_flat)
            for index in bad:
                axes = np.flatnonzero(tie[:, index])
                need(len(axes) > 0, 'nearest_neighbor_independent_mapping_mismatch')
                possibilities = [nearest[:, index].copy()]
                for axis in axes:
                    lower = int(np.floor(continuous[axis, index]))
                    possibilities = [np.array([lower if d == axis else p[d] for d in range(3)]) for p in possibilities] + [np.array([lower + 1 if d == axis else p[d] for d in range(3)]) for p in possibilities]
                candidates = [int(source_labels[p[2], p[1], p[0]]) if ((p >= 0) & (p < size)).all() else 0 for p in possibilities]
                need(int(actual_flat[index]) in candidates, 'nearest_neighbor_tie_not_physically_nearest')
                tie_label_alternatives += 1
    return expected, {'outside_source_nearest_support_voxels': outside,
                      'half_voxel_tie_target_centres': ties,
                      'equally_nearest_alternative_labels_used': tie_label_alternatives,
                      'half_voxel_tie_tolerance_source_voxels': NN_TIE_TOL}


def counts(array):
    return {str(value): int((array == value).sum()) for value in (0, 1, 2)}


def prepare(mri_path, prediction_path, context, output_path, sidecar_path, private_report_path):
    mri_path, prediction_path, output_path, sidecar_path, private_report_path = [Path(p) for p in (mri_path, prediction_path, output_path, sidecar_path, private_report_path)]
    need(len({p.resolve() for p in (mri_path, prediction_path, output_path, sidecar_path, private_report_path)}) == 5, 'input_output_paths_overlap')
    need(not output_path.exists() and not sidecar_path.exists() and not private_report_path.exists(), 'output_already_exists_preserve_and_inspect')
    need(output_path.parent.resolve() not in private_report_path.resolve().parents, 'private_report_inside_reader_case')
    required = ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256', 'knee_side', 'source_prediction', 'existing_split')
    need(all(key in context for key in required), 'source_context_binding_incomplete')
    source_prediction = context['source_prediction']
    need(isinstance(source_prediction, dict) and all(isinstance(source_prediction.get(k), str) and source_prediction[k].strip() for k in ('sha256', 'pipeline_version', 'model_version', 'identity')), 'source_prediction_provenance_incomplete')
    mri_hash, prediction_hash = sha256(mri_path), sha256(prediction_path)
    need(mri_hash == context['image_sha256'], 'MRI_binding_checksum_mismatch')
    need(prediction_hash == source_prediction['sha256'], 'prediction_checksum_mismatch')
    case_path = mri_path.parent / 'case.json'
    need(case_path.is_file() and not case_path.is_symlink(), 'MRI_case_identity_metadata_required')
    case_hash = sha256(case_path)
    case = json.loads(case_path.read_text())
    for field in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256', 'knee_side'):
        need(case.get(field) == context[field], 'MRI_case_context_identity_mismatch_' + field)
    for field in ('participant_id', 'visit_month', 'original_visit_code', 'archive_series_number', 'source_study_date'):
        if field in context:
            need(str(case.get(field)) == str(context[field]), 'MRI_case_context_source_mismatch_' + field)
    reference = read_reference(mri_path)
    native_affine = affine_lps(reference)
    need(tuple(case['dimensions_xyz']) == reference.GetSize(), 'MRI_case_dimensions_mismatch')
    metadata_affine = np.eye(4)
    metadata_affine[:3, :3] = np.asarray(case['direction_lps_columns']) @ np.diag(case['spacing_xyz_mm'])
    metadata_affine[:3, 3] = case['origin_lps_mm']
    check_nifti(mri_path, reference.GetSize(), metadata_affine)
    source_header = check_nifti(prediction_path)
    raw_mask_storage(prediction_path)
    original = sitk.ReadImage(str(prediction_path))
    need(original.GetDimension() == 3 and original.GetNumberOfComponentsPerPixel() == 1, 'prediction_not_scalar_3d')
    source_affine = affine_lps(original)
    need(np.allclose(original.GetSpacing(), [.5, .5, .5], rtol=0, atol=1e-6), 'prediction_not_documented_half_mm_release_grid')
    recorded_source_size = context.get('source_grid_dimensions_xyz', context.get('expected_source_dimensions_xyz'))
    if context.get('source_grid_dimensions_xyz') and context.get('expected_source_dimensions_xyz'):
        need(context['source_grid_dimensions_xyz'] == context['expected_source_dimensions_xyz'], 'conflicting_recorded_source_dimensions')
    if recorded_source_size:
        need(tuple(original.GetSize()) == tuple(int(x) for x in recorded_source_size), 'source_grid_differs_from_existing_pipeline_record')
    expected_iso = native_affine.copy()
    expected_iso[:3, :3] = np.asarray(reference.GetDirection()).reshape(3, 3) * .5
    points = corners(original.GetSize())
    frame_error = float(np.linalg.norm((world(source_affine, points) - world(expected_iso, points))[:, :3], axis=1).max())
    need(frame_error <= GRID_TOL_MM, 'source_prediction_frame_not_native_MRI_derived_iso_grid')
    source_array = sitk.GetArrayFromImage(original)
    labels, assignment = label_existing_binary(source_array, source_affine, context['knee_side'], context['existing_split'])
    categorical = image_from_source_labels(labels, original)
    resampled = sitk.Resample(categorical, reference, sitk.Transform(3, sitk.sitkIdentity), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    prepared = sitk.GetArrayFromImage(resampled)
    need(tuple(prepared.shape[::-1]) == reference.GetSize() and np.isin(prepared, [0, 1, 2]).all(), 'prepared_labels_or_extent_invalid')
    need((prepared > 0).any(), 'resampling_lost_all_predicted_foreground_unresolved')
    _, independent = physical_nearest(labels, source_affine, native_affine, reference.GetSize(), prepared)
    need(independent['outside_source_nearest_support_voxels'] == 0, 'native_MRI_centres_not_covered_by_prediction_grid')
    back = sitk.GetArrayFromImage(sitk.Resample(resampled, categorical, sitk.Transform(3, sitk.sitkIdentity), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8))
    source_counts, prepared_counts = counts(labels), counts(prepared)
    source_voxel_mm3, target_voxel_mm3 = float(np.prod(original.GetSpacing())), float(np.prod(reference.GetSpacing()))
    round_trip = {}
    for value in (1, 2):
        a, b = labels == value, back == value
        denominator = int(a.sum() + b.sum())
        round_trip[str(value)] = {'dice': float(2 * (a & b).sum() / denominator) if denominator else None,
                                  'source_voxels_not_recovered': int((a & ~b).sum()),
                                  'round_trip_new_source_grid_voxels': int((~a & b).sum())}
    need(sha256(mri_path) == mri_hash and sha256(prediction_path) == prediction_hash and sha256(case_path) == case_hash, 'source_changed_during_preparation')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    private_report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name('.pending-' + uuid.uuid4().hex + '.nii.gz')
    try:
        sitk.WriteImage(resampled, str(temporary), True)
        saved_header = check_nifti(temporary, reference.GetSize(), native_affine)
        raw_mask_storage(temporary)
        reopened = sitk.ReadImage(str(temporary))
        need(np.array_equal(sitk.GetArrayFromImage(reopened), prepared), 'saved_prepared_voxels_changed')
        prepared_hash = sha256(temporary)
        transformation = {'method': 'nearest_neighbor_physical_identity', 'source_grid': grid(original), 'target_grid': grid(reference),
                          'coordinate_transform_LPS_4x4': np.eye(4).tolist(), 'existing_compartment_assignment': assignment,
                          'source_frame_max_corner_difference_from_native_derived_iso_mm': frame_error,
                          'no_filtering_smoothing_filling_or_fragment_removal': True}
        verification = {'status': 'verified', 'native_grid_match': True, 'independent_target_voxel_mapping_match': True,
                        'output_labels_valid': True, 'scope': 'Technical input suitability for correction; not anatomical accuracy or expert review.'}
        sidecar = {'schema_version': 'meniscus_starting_mask/1', 'case_key': context['case_key'], 'source_series_key': context['source_series_key'],
                   'series_instance_uid': context['series_instance_uid'], 'image_sha256': mri_hash, 'prepared_mask_sha256': prepared_hash,
                   'label_mapping': LABELS, 'status': 'unreviewed_automated_prediction',
                   'source_prediction': {key: value for key, value in source_prediction.items() if key in ('sha256', 'pipeline_version', 'model_version', 'identity', 'model_sha256')},
                   'transformation': transformation, 'verification': verification}
        report = {'schema_version': VERSION, 'prepared_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'passed': True,
                  'source_context': copy.deepcopy(context), 'MRI_path': str(mri_path), 'case_metadata_sha256': case_hash, 'original_prediction_path': str(prediction_path),
                  'output_path': str(output_path), 'source_prediction_header': source_header, 'saved_mask_header': saved_header,
                  'source_and_MRI_bytes_unchanged': True, 'independent_mapping': independent, 'source_label_counts': source_counts,
                  'prepared_label_counts': prepared_counts, 'source_label_volumes_mm3': {k: n * source_voxel_mm3 for k, n in source_counts.items()},
                  'prepared_label_volumes_mm3': {k: n * target_voxel_mm3 for k, n in prepared_counts.items()},
                  'categorical_round_trip_change': round_trip, 'sidecar': sidecar,
                  'resampling_limit': 'Nearest-neighbour sampling may remove/add small source-grid features between acquired planes. No explicit anatomical filtering, smoothing, filling or fragment removal is performed.',
                  'software': {'numpy': np.__version__, 'SimpleITK': sitk.Version_VersionString()}}
        private_report_path.write_text(json.dumps(report, indent=2) + '\n')
        private_report_path.chmod(0o600)
        os.replace(temporary, output_path)
        sidecar_path.write_text(json.dumps(sidecar, indent=2) + '\n')
        need(sha256(mri_path) == mri_hash and sha256(prediction_path) == prediction_hash and sha256(case_path) == case_hash, 'source_changed_after_preparation')
        return report
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('mri', 'prediction', 'source-json', 'output', 'provenance', 'private-report'):
        parser.add_argument('--' + field, required=True, type=Path)
    args = parser.parse_args()
    try:
        report = prepare(args.mri, args.prediction, json.loads(args.source_json.read_text()), args.output, args.provenance, args.private_report)
    except StartingMaskError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        return 1
    print(json.dumps({'passed': report['passed'], 'prepared_label_counts': report['prepared_label_counts']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
