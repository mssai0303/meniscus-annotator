#!/usr/bin/env python3
"""Read and technically validate an exported regional checkpoint or results ZIP.

This is an inspectable loading example, not a downstream training integration.
Current regional expert protocol is pending, so every returned training target
is -1 (excluded). The regional label image itself remains intact for inspection.
No source MRI is required; --source-image additionally verifies original bytes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

import numpy as np

application_root = Path(__file__).resolve().parents[1]
module_root = (application_root if (application_root / 'MeniscusAnnotatorLib').is_dir()
               else application_root / 'lib' / 'Slicer-5.12' / 'qt-scripted-modules')
sys.path.insert(0, str(module_root))
from MeniscusAnnotatorLib.core import (ValidationError, need, sha256, canonical, read_json,
                                     check_nifti, validity_array, research_eligibility_array, eligibility_metadata, APP_VERSION, check_output_marker, validate_research_metadata)
from MeniscusAnnotatorLib import regions as regional

BASE_FILES = {'annotation.json', 'slice_review.csv', 'labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz', 'segmentation.seg.nrrd'}


def _read_directory(folder, source_image=None):
    import csv
    folder = Path(folder)
    manifest = read_json(folder/'manifest.json')
    need(manifest.get('schema_version') == 'meniscus_checkpoint/1', 'Unsupported checkpoint schema.')
    need(manifest.get('regional_extension') == {'schema_version': regional.EXTENSION_SCHEMA, 'protocol_status': 'pending_expert_protocol', 'research_approved': False},
         'An intact optional regional extension is required; whole-only files cannot be treated as regional labels.')
    expected_files = BASE_FILES | regional.REGIONAL_FILES
    if 'research_eligibility' in manifest:
        expected_files |= {'research_eligibility.nii.gz'}
    need(set(manifest.get('files_sha256', {})) == expected_files,
         'Regional checkpoint payload is incomplete or has unsupported files.')
    for name, digest in manifest['files_sha256'].items():
        need((folder/name).is_file() and not (folder/name).is_symlink() and sha256(folder/name) == digest,
             'Checkpoint checksum failed: ' + name)
    primary = read_json(folder/'annotation.json')
    need(primary.get('schema_version') == 'meniscus_annotation/1' and primary.get('label_mapping') == {'0': 'background', '1': 'medial meniscus', '2': 'lateral meniscus'},
         'Unsupported whole-meniscus metadata or label mapping.')
    validate_research_metadata(primary)
    source = primary.get('source')
    need(isinstance(source, dict) and canonical(source) == primary.get('source_identity') == manifest.get('source_identity')
         and source.get('image_sha256') == primary.get('source_image_sha256') == manifest.get('source_image_sha256'),
         'Source-image identity and saved provenance disagree.')
    shape = tuple(source['dimensions_xyz'])
    spacing = np.asarray(source['spacing_xyz_mm'], dtype=float)
    direction = np.asarray(source['direction_lps_columns'], dtype=float)
    origin = np.asarray(source['origin_lps_mm'], dtype=float)
    need(len(shape) == 3 and all(type(v) is int and v > 0 for v in shape) and spacing.shape == (3,)
         and origin.shape == (3,) and direction.shape == (3, 3) and np.isfinite(spacing).all()
         and (spacing > 0).all() and np.isfinite(origin).all() and np.isfinite(direction).all()
         and np.allclose(direction.T@direction, np.eye(3), atol=1e-5, rtol=0), 'Recorded source geometry is invalid.')
    affine_lps = np.eye(4)
    affine_lps[:3, :3] = direction @ np.diag(spacing)
    affine_lps[:3, 3] = origin
    affine_ras = np.diag([-1, -1, 1, 1]) @ affine_lps
    if source_image is not None:
        need(sha256(source_image) == primary['source_image_sha256'], 'Provided source image has the wrong checksum.')
        check_nifti(source_image, shape, affine_ras)
    arrays = {name: np.asarray(check_nifti(folder/name, shape, affine_ras, True).dataobj).transpose(2, 1, 0).copy()
              for name in ('labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz', 'regions.nii.gz', 'regional_uncertainty.nii.gz', 'regional_validity.nii.gz')}
    for name in arrays:
        check_output_marker(check_nifti(folder/name, shape, affine_ras, True), primary, regional=name.startswith('region'))
    whole, whole_uncertainty = arrays['labels.nii.gz'], arrays['uncertainty.nii.gz']
    if primary.get('app_version') == APP_VERSION:
        need(manifest.get('research_eligibility') == eligibility_metadata(primary), 'Missing or inconsistent research eligibility metadata.')
        eligibility_image = check_nifti(folder/'research_eligibility.nii.gz', shape, affine_ras, True)
        check_output_marker(eligibility_image, primary)
        need(np.array_equal(np.asarray(eligibility_image.dataobj).transpose(2, 1, 0), research_eligibility_array(primary, whole_uncertainty)), 'Research eligibility disagrees with protocol, approval or practice context.')
    need(np.isin(whole, [0, 1, 2]).all() and np.isin(whole_uncertainty, [0, 1]).all(), 'Whole labels or uncertainty have invalid values.')
    review = primary.get('review')
    need(isinstance(review, list) and len(review) == shape[2]
         and all(row.get('slice_index') == k and all(type(row.get(f)) is bool for f in ('reviewed', 'flag'))
                 and isinstance(row.get('note'), str) for k, row in enumerate(review)), 'Whole review metadata is incomplete.')
    with (folder/'slice_review.csv').open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        need(reader.fieldnames == ['slice_index', 'displayed_slice', 'status', 'attention_flag', 'note'], 'Whole review CSV columns are invalid.')
        expected = [{'slice_index': str(row['slice_index']), 'displayed_slice': str(row['slice_index']+1), 'status': 'reviewed' if row['reviewed'] else 'not_reviewed',
                     'attention_flag': str(int(row['flag'])), 'note': row['note']} for row in review]
        need(list(reader) == expected, 'Whole review CSV disagrees with metadata.')
    need(np.array_equal(arrays['validity.nii.gz'], validity_array(primary, whole_uncertainty)), 'Whole validity is inconsistent with its saved review and practice records.')
    state = read_json(folder/'regions.json')
    region_array, region_uncertain = arrays['regions.nii.gz'], arrays['regional_uncertainty.nii.gz']
    regional.validate(whole, region_array, region_uncertain, state, primary)
    with (folder/'regional_review.csv').open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        need(reader.fieldnames == regional.REVIEW_FIELDS and list(reader) == regional.review_rows(state), 'Regional review CSV disagrees with metadata.')
    expected_validity = regional.validity(whole, whole_uncertainty, region_array, region_uncertain, state, primary)
    need(np.array_equal(arrays['regional_validity.nii.gz'], expected_validity), 'Regional validity is inconsistent or falsely accepts protocol-pending tissue.')
    # Explicit exclusion is represented as -1, not ordinary class 0/background.
    # Future accepted training needs a new released expert contract and checker;
    # no file edit can promote this pending-only reader to acceptance.
    targets = np.full(whole.shape, -1, dtype=np.int16)
    return {'regions': region_array, 'regional_uncertainty': region_uncertain,
            'regional_validity': expected_validity, 'whole_labels': whole,
            'training_targets': targets, 'accepted_regional_voxels': 0,
            'regional_state': copy.deepcopy(state), 'primary_state': copy.deepcopy(primary),
            'summary': regional.completeness(whole, region_array, region_uncertain, state),
            'exclusion_reasons': regional.completion_errors(whole, whole_uncertainty, region_array, region_uncertain, state, primary),
            'source_bytes_verified': source_image is not None,
            'scope': 'Technical native-grid loading example. Pending/unassigned/uncertain/unreviewed/practice regions excluded. No anatomical validation or actual downstream training-loader integration.'}


def read_regional_annotation(path, case_key=None, source_image=None):
    """Read an immutable checkpoint directory, or a selected case in a results ZIP."""
    path = Path(path)
    if path.is_dir():
        return _read_directory(path, source_image)
    need(path.is_file() and zipfile.is_zipfile(path), 'Select a checkpoint folder or complete results ZIP.')
    with zipfile.ZipFile(path) as archive:
        results = json.loads(archive.read('results.json'))
        need(results.get('schema_version') == 'meniscus_results/1' and isinstance(results.get('cases'), list), 'Unsupported results ZIP metadata.')
        candidates = [r for r in results['cases'] if case_key is None or r.get('case_key') == case_key]
        need(len(candidates) == 1, 'Select exactly one exported case using --case-key when the ZIP has multiple cases.')
        receipt = candidates[0]
        need(re.fullmatch(r'cases/[0-9a-f]{24}', receipt.get('folder', '')) is not None, 'Export contains an unsafe case folder.')
        base = receipt['folder'] + '/'
        manifest_bytes = archive.read(base+'manifest.json')
        need(hashlib.sha256(manifest_bytes).hexdigest() == receipt.get('manifest_sha256'), 'Exported manifest checksum differs from results metadata.')
        checkpoint_manifest = json.loads(manifest_bytes)
        need(checkpoint_manifest.get('regional_extension') == {'schema_version': regional.EXTENSION_SCHEMA, 'protocol_status': 'pending_expert_protocol', 'research_approved': False}, 'The selected exported checkpoint has no supported regional extension.')
        expected_files = BASE_FILES | regional.REGIONAL_FILES
        if 'research_eligibility' in checkpoint_manifest:
            expected_files |= {'research_eligibility.nii.gz'}
        need(set(checkpoint_manifest.get('files_sha256', {})) == expected_files, 'The selected regional export is incomplete.')
        with tempfile.TemporaryDirectory(prefix='meniscus-regional-reader-') as temporary:
            destination = Path(temporary)
            (destination/'manifest.json').write_bytes(manifest_bytes)
            # Fixed names only: never extract paths supplied by an untrusted ZIP.
            for name in expected_files:
                (destination/name).write_bytes(archive.read(base+name))
            result = _read_directory(destination, source_image)
            need(result['primary_state']['case_key'] == receipt['case_key']
                 and result['primary_state']['source_identity'] == receipt['source_identity'], 'Export receipt and checkpoint identify different cases.')
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint_or_zip', type=Path)
    parser.add_argument('--case-key')
    parser.add_argument('--source-image', type=Path)
    args = parser.parse_args()
    try:
        result = read_regional_annotation(args.checkpoint_or_zip, args.case_key, args.source_image)
        print(json.dumps({'technical_read_passed': True, 'accepted_regional_voxels': result['accepted_regional_voxels'],
                          'protocol_status': result['regional_state']['protocol']['status'],
                          'unassigned_voxels': result['summary']['unassigned_voxels'],
                          'source_bytes_verified': result['source_bytes_verified'],
                          'excluded_target_value': -1, 'exclusion_reasons': result['exclusion_reasons'], 'scope': result['scope']}, indent=2))
        return 0
    except (ValidationError, OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        print('Regional read failed: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
