"""Prepare an explicitly documented, provisional case-specific region attribution.

This is separate from the original pipeline's compartment method. It never
changes V20 thresholds, infers a cut, removes fragments, or claims expert
anatomical approval. A checksum-bound MRI-landmark evidence record and physical
LPS plane are mandatory. All original source foreground and its acquired-grid
nearest-neighbour foreground must remain exactly unchanged.
"""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import uuid

import numpy as np
import SimpleITK as sitk

from native_mri_package import check_nifti, corners, sha256, world
from prepare_starting_mask import (GRID_TOL_MM, LABELS, StartingMaskError, affine_lps,
                                   counts, grid, image_from_source_labels, need,
                                   physical_nearest, raw_mask_storage, read_reference)

VERSION = 'prepare_case_resolution/1'
METHOD = 'case_specific_MRI_landmark_empty_gap/1'
ASSIGNMENT_STATUS = 'provisional_region_attribution_for_correction'
IDENTITY_FIELDS = ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')
LANDMARKS = ('fibular_head', 'both_tibiofemoral_compartments', 'intercondylar_notch')
EMPTY_PLANE_TOL_MM = 1e-5


def checked_assignment(path, context, native_slices):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), 'case_assignment_metadata_required')
    assignment_hash = sha256(path)
    assignment = json.loads(path.read_text(encoding='utf-8'))
    need(assignment.get('schema_version') == 'meniscus_case_compartment_assignment/1' and assignment.get('method') == METHOD, 'unsupported_case_assignment_method')
    need(all(assignment.get(field) == context[field] for field in IDENTITY_FIELDS), 'assignment_case_or_MRI_identity_mismatch')
    need(assignment.get('source_prediction_sha256') == context['source_prediction']['sha256'], 'assignment_source_prediction_checksum_mismatch')
    need(assignment.get('anatomical_assignment_status') == ASSIGNMENT_STATUS and assignment.get('expert_approval') is False, 'case_assignment_must_remain_provisional_not_expert_approved')
    old = assignment.get('original_pipeline_assignment')
    need(isinstance(old, dict) and old.get('status') == 'ok_whole' and old.get('split_method') == 'whole' and isinstance(old.get('reason'), str) and old['reason'].strip(), 'original_pipeline_failure_must_be_preserved')
    existing = context.get('existing_split', {})
    need(isinstance(existing, dict) and existing.get('split_method') == 'whole' and existing.get('split_cut_plane') in (None, ''), 'case_resolution_cannot_replace_an_existing_pipeline_assignment')
    evidence = assignment.get('evidence')
    need(isinstance(evidence, dict) and isinstance(evidence.get('path'), str) and evidence['path'].strip() and isinstance(evidence.get('sha256'), str), 'bound_landmark_evidence_required')
    evidence_path = Path(evidence['path'])
    if not evidence_path.is_absolute():
        evidence_path = path.parent / evidence_path
    need(evidence_path.is_file() and not evidence_path.is_symlink() and sha256(evidence_path) == evidence['sha256'], 'landmark_evidence_checksum_mismatch')
    observations = json.loads(evidence_path.read_text(encoding='utf-8'))
    need(observations.get('schema_version') == 'meniscus_case_anatomy_evidence/1', 'unsupported_landmark_evidence_schema')
    need(all(observations.get(field) == context[field] for field in IDENTITY_FIELDS) and observations.get('source_prediction_sha256') == context['source_prediction']['sha256'], 'landmark_evidence_case_or_checksum_mismatch')
    need(observations.get('supports_provisional_region_attribution') is True and observations.get('expert_approval') is False, 'landmark_evidence_must_be_explicit_and_provisional')
    rationale = observations.get('landmarks')
    need(isinstance(rationale, dict) and all(isinstance(rationale.get(key), str) and rationale[key].strip() for key in LANDMARKS), 'MRI_landmark_rationale_incomplete')
    attention = assignment.get('attention_native_slices')
    need(isinstance(attention, list) and attention and all(type(k) is int and 0 <= k < native_slices for k in attention) and len(set(attention)) == len(attention), 'explicit_native_attention_slices_required')
    need(observations.get('attention_native_slices') == attention and isinstance(observations.get('attention_reason'), str) and observations['attention_reason'].strip(), 'central_fragment_attention_evidence_required')
    plane = assignment.get('physical_plane_lps')
    need(isinstance(plane, dict) and plane.get('medial_side') in ('positive', 'negative'), 'physical_plane_assignment_required')
    normal, point = np.asarray(plane.get('normal'), dtype=float), np.asarray(plane.get('point_mm'), dtype=float)
    need(normal.shape == point.shape == (3,) and np.isfinite(normal).all() and np.isfinite(point).all() and abs(np.linalg.norm(normal) - 1) <= 1e-5, 'invalid_explicit_physical_plane')
    normal = normal / np.linalg.norm(normal)
    return assignment, assignment_hash, evidence_path, observations, normal, point


def partition_by_physical_plane(binary, source_affine, normal, point, medial_side, knee_side):
    """Attribute unchanged foreground by the explicit documented physical-plane sign."""
    need(np.issubdtype(binary.dtype, np.integer) and np.isin(binary, [0, 1]).all() and binary.any(), 'source_prediction_must_be_nonempty_binary')
    need(knee_side in ('L', 'R') and medial_side in ('positive', 'negative'), 'explicit_anatomical_assignment_side_required')
    kji = np.argwhere(binary > 0)
    homogeneous = np.column_stack((kji[:, ::-1], np.ones(len(kji))))
    physical = np.einsum('ij,kj->ki', source_affine[:3], homogeneous, optimize=False)
    signed = np.einsum('ij,j->i', physical - point, normal, optimize=False)
    need(np.isfinite(signed).all(), 'nonfinite_physical_plane_distances')
    # A plane through adjacent positive voxel supports is not an empty gap even
    # if no positive voxel centre lies exactly on the plane.
    half_support_mm = float(.5 * np.abs(np.einsum('i,ij->j', normal, source_affine[:3, :3], optimize=False)).sum())
    need((np.abs(signed) > half_support_mm + EMPTY_PLANE_TOL_MM).all(), 'physical_plane_does_not_cross_an_empty_foreground_gap')
    positive, negative = signed > 0, signed < 0
    need(positive.any() and negative.any(), 'physical_plane_does_not_separate_two_foreground_regions')
    medial = positive if medial_side == 'positive' else negative
    lateral = ~medial
    x_medial, x_lateral = float(physical[medial, 0].mean()), float(physical[lateral, 0].mean())
    need((x_medial > x_lateral + GRID_TOL_MM) if knee_side == 'R' else (x_medial < x_lateral - GRID_TOL_MM), 'physical_plane_label_assignment_conflicts_with_LPS_knee_side')
    labels = np.zeros(binary.shape, dtype=np.uint8)
    labels[tuple(kji[medial].T)] = 1
    labels[tuple(kji[lateral].T)] = 2
    need(np.array_equal(labels > 0, binary > 0), 'case_partition_changed_source_foreground')
    negative_nearest = float(signed[negative].max())
    positive_nearest = float(signed[positive].min())
    return labels, {'method': METHOD, 'physical_plane_lps': {'normal': normal.tolist(), 'point_mm': point.tolist(), 'medial_side': medial_side},
                    'medial_centroid_lps_mm': physical[medial].mean(axis=0).tolist(), 'lateral_centroid_lps_mm': physical[lateral].mean(axis=0).tolist(),
                    'empty_gap_voxel_support_bounds_signed_mm': [negative_nearest + half_support_mm, positive_nearest - half_support_mm],
                    'empty_gap_width_mm': positive_nearest - negative_nearest - 2 * half_support_mm,
                    'source_foreground_minimum_abs_plane_distance_mm': float(np.abs(signed).min()),
                    'projected_source_voxel_half_support_mm': half_support_mm, 'source_foreground_exactly_preserved': True,
                    'assignment_basis': 'Explicit MRI-landmark evidence plus physical LPS; not a new global split rule or recovered V20 cut.'}


def prepare(mri, prediction, context, assignment_json, output, provenance, private_report):
    mri, prediction, assignment_json, output, provenance, private_report = [Path(path) for path in (mri, prediction, assignment_json, output, provenance, private_report)]
    need(len({path.resolve() for path in (mri, prediction, assignment_json, output, provenance, private_report)}) == 6, 'resolution_input_output_paths_overlap')
    need(not any(path.exists() for path in (output, provenance, private_report)), 'resolution_outputs_already_exist_preserve_and_inspect')
    need(output.parent.resolve() not in private_report.resolve().parents and private_report.resolve() != output.parent.resolve(), 'private_report_inside_reader_case')
    case_path = mri.parent / 'case.json'
    need(case_path.is_file() and not case_path.is_symlink(), 'MRI_case_metadata_required')
    case_hash, mri_hash, prediction_hash = sha256(case_path), sha256(mri), sha256(prediction)
    case = json.loads(case_path.read_text(encoding='utf-8'))
    need(all(isinstance(case.get(field), str) and case[field].strip() and isinstance(context.get(field), str) and context[field].strip() for field in IDENTITY_FIELDS), 'case_resolution_identity_metadata_incomplete')
    for field in (*IDENTITY_FIELDS, 'knee_side'):
        need(context.get(field) == case.get(field), 'case_resolution_context_identity_mismatch')
    need(mri_hash == case['image_sha256'] == context['image_sha256'], 'case_resolution_MRI_checksum_mismatch')
    source_prediction = context.get('source_prediction')
    need(isinstance(source_prediction, dict) and source_prediction.get('sha256') == prediction_hash and all(isinstance(source_prediction.get(key), str) and source_prediction[key].strip() for key in ('pipeline_version', 'model_version', 'identity')), 'case_resolution_prediction_provenance_mismatch')
    reference = read_reference(mri)
    need(tuple(case['dimensions_xyz']) == reference.GetSize(), 'case_resolution_MRI_dimension_mismatch')
    metadata_affine = np.eye(4)
    metadata_affine[:3, :3] = np.asarray(case['direction_lps_columns']) @ np.diag(case['spacing_xyz_mm']); metadata_affine[:3, 3] = case['origin_lps_mm']
    check_nifti(mri, reference.GetSize(), metadata_affine)
    target_affine = affine_lps(reference)
    assignment, assignment_hash, evidence_path, observations, normal, point = checked_assignment(assignment_json, context, reference.GetSize()[2])
    evidence_hash = sha256(evidence_path)
    source_header = check_nifti(prediction); raw_mask_storage(prediction)
    original = sitk.ReadImage(str(prediction))
    need(original.GetDimension() == 3 and original.GetNumberOfComponentsPerPixel() == 1 and np.allclose(original.GetSpacing(), [.5, .5, .5], atol=1e-6, rtol=0), 'case_resolution_requires_documented_binary_half_mm_release')
    expected_size = context.get('source_grid_dimensions_xyz', context.get('expected_source_dimensions_xyz'))
    need(expected_size is not None and tuple(original.GetSize()) == tuple(int(n) for n in expected_size), 'case_resolution_source_grid_dimensions_mismatch')
    source_affine = affine_lps(original)
    expected_affine = target_affine.copy(); expected_affine[:3, :3] = np.asarray(reference.GetDirection()).reshape(3, 3) * .5
    points = corners(original.GetSize())
    frame_error = float(np.linalg.norm((world(source_affine, points) - world(expected_affine, points))[:, :3], axis=1).max())
    need(frame_error <= GRID_TOL_MM, 'case_resolution_source_frame_not_MRI_derived')
    binary = sitk.GetArrayFromImage(original)
    labels, partition = partition_by_physical_plane(binary, source_affine, normal, point, assignment['physical_plane_lps']['medial_side'], case['knee_side'])
    categorical = image_from_source_labels(labels, original)
    transform = sitk.Transform(3, sitk.sitkIdentity)
    mapped = sitk.Resample(categorical, reference, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    prepared = sitk.GetArrayFromImage(mapped)
    binary_native = sitk.GetArrayFromImage(sitk.Resample(original, reference, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8))
    need(np.array_equal(prepared > 0, binary_native > 0), 'case_resolution_changed_original_native_binary_foreground')
    need(set(int(n) for n in np.unique(prepared)) <= {0, 1, 2} and (prepared == 1).any() and (prepared == 2).any(), 'case_resolution_native_labels_invalid_or_compartment_lost')
    _, independent = physical_nearest(labels, source_affine, target_affine, reference.GetSize(), prepared)
    need(independent['outside_source_nearest_support_voxels'] == 0, 'case_resolution_native_centres_outside_prediction_grid')
    bound_hashes = {mri: mri_hash, prediction: prediction_hash, case_path: case_hash, assignment_json: assignment_hash, evidence_path: evidence_hash}
    need(all(sha256(path) == digest for path, digest in bound_hashes.items()), 'bound_resolution_source_or_evidence_changed')
    output.parent.mkdir(parents=True, exist_ok=True); provenance.parent.mkdir(parents=True, exist_ok=True); private_report.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name('.pending-case-resolution-' + uuid.uuid4().hex + '.nii.gz')
    try:
        sitk.WriteImage(mapped, str(temporary), True)
        saved_header = check_nifti(temporary, reference.GetSize(), target_affine); raw_mask_storage(temporary)
        need(np.array_equal(sitk.GetArrayFromImage(sitk.ReadImage(str(temporary))), prepared), 'case_resolution_saved_mask_voxels_changed')
        prepared_hash = sha256(temporary)
        transformation = {'method': METHOD + '; nearest_neighbor_physical_identity', 'source_grid': grid(original), 'target_grid': grid(reference),
                          'coordinate_transform_LPS_4x4': np.eye(4).tolist(), 'case_specific_compartment_assignment': partition,
                          'original_pipeline_assignment': {key: copy.deepcopy(assignment['original_pipeline_assignment'][key]) for key in ('status', 'split_method', 'reason')},
                          'case_assignment_record_sha256': assignment_hash, 'MRI_landmark_evidence_sha256': evidence_hash,
                          'no_filtering_smoothing_filling_fragment_removal_or_V20_threshold_change': True,
                          'source_frame_max_corner_difference_from_native_derived_iso_mm': frame_error}
        verification = {'status': 'verified', 'native_grid_match': True, 'independent_target_voxel_mapping_match': True, 'output_labels_valid': True,
                        'anatomical_assignment_status': ASSIGNMENT_STATUS, 'expert_approval': False,
                        'source_foreground_exactly_preserved': True, 'native_binary_foreground_exactly_preserved': True,
                        'attention_native_slices_zero_based': assignment['attention_native_slices'], 'attention_reason': observations['attention_reason'],
                        'scope': 'Technical region attribution for unreviewed correction initialization, not confirmed voxel anatomy or expert acceptance.'}
        sidecar = {'schema_version': 'meniscus_starting_mask/1', **{key: case[key] for key in IDENTITY_FIELDS}, 'prepared_mask_sha256': prepared_hash,
                   'label_mapping': LABELS, 'status': 'unreviewed_automated_prediction',
                   'source_prediction': {key: value for key, value in source_prediction.items() if key in ('sha256', 'pipeline_version', 'model_version', 'identity', 'model_sha256')},
                   'transformation': transformation, 'verification': verification}
        report = {'schema_version': VERSION, 'prepared_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'passed': True,
                  'source_context': copy.deepcopy(context), 'case_assignment': assignment, 'MRI_landmark_evidence': observations,
                  'input_paths': {'MRI': str(mri), 'original_prediction': str(prediction), 'case_metadata': str(case_path), 'case_assignment': str(assignment_json), 'evidence': str(evidence_path)},
                  'original_input_and_evidence_hashes': {str(path): digest for path, digest in bound_hashes.items()}, 'source_and_MRI_bytes_unchanged': True,
                  'source_prediction_header': source_header, 'saved_mask_header': saved_header, 'independent_mapping': independent,
                  'source_label_counts': counts(labels), 'prepared_label_counts': counts(prepared), 'source_total_foreground_voxels': int(binary.sum()),
                  'native_binary_foreground_voxels': int((binary_native > 0).sum()), 'native_binary_foreground_exactly_preserved': True,
                  'sidecar': sidecar, 'software': {'numpy': np.__version__, 'SimpleITK': sitk.Version_VersionString()}}
        with private_report.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2); stream.write('\n')
        private_report.chmod(0o600)
        os.replace(temporary, output)
        with provenance.open('x', encoding='utf-8') as stream:
            json.dump(sidecar, stream, indent=2); stream.write('\n')
        need(all(sha256(path) == digest for path, digest in bound_hashes.items()), 'bound_resolution_source_or_evidence_changed_after_write')
        return report
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('mri', 'prediction', 'context', 'assignment-json', 'output', 'provenance', 'private-report'):
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    report = prepare(args.mri, args.prediction, json.loads(args.context.read_text(encoding='utf-8')), args.assignment_json, args.output, args.provenance, args.private_report)
    print(json.dumps({'passed': report['passed'], 'native_binary_foreground_exactly_preserved': True, 'prepared_label_counts': report['prepared_label_counts'], 'anatomical_assignment_status': ASSIGNMENT_STATUS, 'expert_approval': False}))


if __name__ == '__main__':
    main()
