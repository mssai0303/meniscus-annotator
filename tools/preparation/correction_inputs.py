"""Prepared correction-input extension of the maintained package checker.

This checks native-grid categorical inputs, provenance bindings and explicit job
permissions. It never writes images/annotations or accepts anatomical accuracy.
The application independently reads the same meniscus_job/1 contract.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import numpy as np
import SimpleITK as sitk

from native_mri_package import check_nifti, sha256, need
from package_layout import checked_case_contents
from correction_resolutions import resolve_registry, FILENAME as RESOLUTION_FILENAME

LABEL_MAPPING = {'0': 'no predicted meniscus', '1': 'medial meniscus', '2': 'lateral meniscus'}
IDENTITY_FIELDS = ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256')
COMMON_FIELDS = frozenset(('schema_version', *IDENTITY_FIELDS, 'status', 'source_prediction', 'verification'))
READY_FIELDS = COMMON_FIELDS | {'prepared_mask_sha256', 'label_mapping', 'transformation'}
UNRESOLVED_FIELDS = COMMON_FIELDS | {'reason'}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def package_relative(root, relative):
    need(isinstance(relative, str) and relative and '\\' not in relative, 'unsafe_correction_mask_path')
    path = PurePosixPath(relative)
    need(not path.is_absolute() and path.as_posix() == relative and '..' not in path.parts, 'unsafe_correction_mask_path')
    file = Path(root).joinpath(*path.parts)
    need(file.resolve().is_relative_to(Path(root).resolve()), 'correction_mask_path_leaves_package')
    for part in (file, *file.parents):
        if part == Path(root):
            break
        need(not part.is_symlink(), 'symlink_in_correction_mask_path')
    return file


def read_json(path):
    need(path.is_file() and not path.is_symlink(), 'missing_or_symlink_correction_metadata')
    return json.loads(path.read_text(encoding='utf-8'))


def validate_correction_package(package, cases, catalog_by_key, layouts, allow_unresolved=False):
    package = Path(package)
    job = read_json(package / 'correction_job.json')
    dataset_identity = canonical(sorted((case['case_key'], canonical(case)) for case in cases))
    need(isinstance(job, dict) and job.get('schema_version') == 'meniscus_job/1' and job.get('dataset_identity') == dataset_identity, 'correction_job_dataset_identity_mismatch')
    protocol = job.get('protocol')
    need(isinstance(protocol, dict) and isinstance(protocol.get('version'), str) and protocol['version'].strip() and protocol.get('status') in ('draft', 'released'), 'correction_job_protocol_invalid')
    rules = job.get('cases')
    need(isinstance(rules, dict) and set(rules) == set(catalog_by_key), 'correction_job_must_cover_every_case_no_blank_fallback')
    expected_files = {'correction_job.json'}
    registry_cases = {case['case_key']: {'metadata': case, 'relative_folder': catalog_by_key[case['case_key']]['relative_folder']} for case in cases}
    resolved_rules, resolution_bindings, registry = resolve_registry(package, job, dataset_identity, registry_cases, need, sha256, read_json)
    rules = dict(rules)
    rules.update(resolved_rules)
    if registry is not None:
        expected_files.add(RESOLUTION_FILENAME)
    ready, unresolved = 0, 0
    prediction_versions, model_versions = set(), set()
    for case in cases:
        key = case['case_key']; relative = catalog_by_key[key]['relative_folder']
        folder = package_relative(package, relative)
        contents = checked_case_contents(folder, layouts[key], correction=True, allow_unresolved=allow_unresolved)
        expected_files.add(relative + '/starting_mask.json')
        metadata = read_json(folder / 'starting_mask.json')
        need(metadata.get('schema_version') == 'meniscus_starting_mask/1', 'unsupported_starting_mask_schema')
        need(all(metadata.get(field) == case[field] for field in IDENTITY_FIELDS), 'starting_mask_case_source_binding_mismatch')
        source = metadata.get('source_prediction')
        need(isinstance(source, dict) and isinstance(source.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', source['sha256']) and all(isinstance(source.get(k), str) and source[k].strip() for k in ('pipeline_version', 'model_version')), 'starting_mask_source_provenance_incomplete')
        prediction_versions.add(source['pipeline_version']);model_versions.add(source['model_version'])
        verification = metadata.get('verification')
        need(isinstance(verification, dict), 'starting_mask_verification_missing')
        rule = rules[key]
        need(isinstance(rule, dict) and rule.get('annotation_mode') == 'correction', 'correction_job_case_cannot_default_to_blank')
        status = metadata.get('status')
        if status == 'unresolved':
            need(allow_unresolved, 'correction_package_incomplete_unresolved_predictions')
            need(set(metadata) == UNRESOLVED_FIELDS and isinstance(metadata.get('reason'), str) and metadata['reason'].strip(), 'unresolved_starting_mask_schema_invalid')
            need('starting_mask.nii.gz' not in contents and verification.get('status') == 'unresolved', 'unresolved_case_has_fake_mask_or_verification')
            need(rule.get('availability') == 'unresolved' and rule.get('starting_mask', 'MISSING') is None and rule.get('reason') == metadata['reason'], 'unresolved_correction_job_not_blocked')
            unresolved += 1
            continue
        need(status == 'unreviewed_automated_prediction' and set(metadata) == READY_FIELDS, 'prepared_mask_must_remain_unreviewed_prediction')
        need(metadata.get('label_mapping') == LABEL_MAPPING, 'starting_mask_label_mapping_invalid')
        transform = metadata.get('transformation')
        need(isinstance(transform, dict) and isinstance(transform.get('method'), str) and transform['method'].strip(), 'starting_mask_transform_provenance_missing')
        need(verification.get('status') == 'verified' and verification.get('native_grid_match') is True and verification.get('independent_target_voxel_mapping_match') is True and verification.get('output_labels_valid') is True, 'starting_mask_technical_verification_not_passed')
        mask = folder / 'starting_mask.nii.gz'
        actual = sha256(mask)
        need(actual == metadata.get('prepared_mask_sha256'), 'prepared_starting_mask_checksum_mismatch')
        spacing = np.asarray(case['spacing_xyz_mm'], dtype=float)
        affine = np.eye(4);affine[:3, :3] = np.asarray(case['direction_lps_columns'], dtype=float) @ np.diag(spacing);affine[:3, 3] = case['origin_lps_mm']
        check_nifti(mask, case['dimensions_xyz'], affine)
        image = sitk.ReadImage(str(mask)); values = sitk.GetArrayFromImage(image)
        need(values.shape == tuple(case['dimensions_xyz'][::-1]) and np.issubdtype(values.dtype, np.integer) and np.isin(values, [0, 1, 2]).all(), 'prepared_mask_values_or_extent_invalid')
        need(np.allclose(image.GetSpacing(), spacing, rtol=0, atol=1e-5) and np.allclose(image.GetOrigin(), case['origin_lps_mm'], rtol=0, atol=.01) and np.allclose(np.asarray(image.GetDirection()).reshape(3, 3), case['direction_lps_columns'], rtol=0, atol=1e-5), 'reopened_starting_mask_grid_mismatch')
        start = rule.get('starting_mask')
        need(rule.get('availability', 'ready') == 'ready' and isinstance(start, dict), 'ready_starting_mask_job_invalid')
        need(start.get('path') == relative + '/starting_mask.nii.gz' and start.get('sha256') == actual and all(isinstance(start.get(k), str) and start[k].strip() for k in ('version', 'source')), 'starting_mask_job_permission_mismatch')
        package_relative(package, start['path'])
        expected_files.add(relative + '/starting_mask.nii.gz')
        ready += 1
    need(len(prediction_versions) == 1 and len(model_versions) == 1, 'mixed_starting_prediction_pipeline_or_model_versions')
    need(allow_unresolved or not unresolved, 'correction_package_incomplete_unresolved_predictions')
    return {'correction_package_complete': ready == len(cases) and unresolved == 0, 'matched_cases': len(cases), 'prepared_masks': ready, 'verified_masks': ready, 'unresolved_cases': unresolved, 'pipeline_versions': sorted(prediction_versions), 'model_versions': sorted(model_versions), 'dataset_identity': dataset_identity,
            'base_job_identity': canonical(job), 'resolved_cases': len(resolution_bindings),
            'case_resolution_identities': sorted(binding['resolution_identity'] for binding in resolution_bindings.values()),
            'scope': 'Unreviewed automated categorical starting inputs; no expert-confirmed anatomy or background.'}, expected_files
