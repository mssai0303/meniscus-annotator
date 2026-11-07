"""Bind an existing prediction-match inventory to unchanged package case metadata.

Writes PRIVATE processing contexts, never a new selection or MRI. Paths and
participant-level records must be outside the software repository.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def optional_number(value):
    if not value:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def build(package, inventory, version_record, native_reports, scc_workspace):
    package, native_reports = Path(package), Path(native_reports)
    version = json.loads(Path(version_record).read_text())
    with Path(inventory).open(newline='') as f:
        matches = list(csv.DictReader(f))
    with (package / 'case_index.csv').open(newline='') as f:
        catalog = list(csv.DictReader(f))
    by_key = {r['case_key']: r for r in matches}
    if len(by_key) != len(matches) or set(by_key) != {r['case_key'] for r in catalog}:
        raise ValueError('prediction_inventory_membership_mismatch')
    output = []
    for row in catalog:
        match = by_key[row['case_key']]
        metadata = json.loads((package / row['relative_folder'] / 'case.json').read_text())
        report = json.loads((native_reports / (row['case_key'] + '.json')).read_text())
        for field in ('case_key', 'participant_id', 'knee_side', 'source_series_key'):
            if metadata[field] != match[field]:
                raise ValueError('prediction_case_identity_mismatch')
        if (metadata['visit_month'] != int(match['visit_month']) or
                metadata['image_sha256'] != match['native_image_sha256'] or
                metadata['series_instance_uid'] != match['native_series_instance_uid']):
            raise ValueError('prediction_acquisition_binding_mismatch')
        if match['match_status'] != 'matched':
            raise ValueError('prediction_not_matched')
        if report['selection']['source_series_key'] != metadata['source_series_key'] or report['saved_volume']['image_sha256'] != metadata['image_sha256']:
            raise ValueError('native_source_report_mismatch')
        identity = '%s/source-row-%s/%s/%s/%s/%s' % (version['release_version'], match['source_inventory_row'], match['archive_visit_folder'], match['participant_id'], match['study_date'], match['archive_series_number'])
        context = {key: metadata[key] for key in ('case_key', 'participant_id', 'visit_month', 'knee_side', 'source_series_key', 'series_instance_uid', 'image_sha256', 'original_visit_code', 'archive_series_number', 'source_study_date')}
        context.update(source_grid_dimensions_xyz=[int(match['iso_nx']), int(match['iso_ny']), int(match['iso_nz'])],
                       source_prediction={'sha256': match['source_prediction_sha256'], 'pipeline_version': version['release_version'] + '; ' + version['pipeline_version'], 'model_version': 'meniscus_v2_best.keras SHA256 ' + version['recorded_inference_model_sha256'], 'model_sha256': version['recorded_inference_model_sha256'], 'identity': identity},
                       existing_split={key: match[key] for key in ('split_cut_plane', 'medial_is_low_index', 'split_method', 'x_low_index_mm', 'x_high_index_mm')})
        output.append({'case_key': metadata['case_key'], 'relative_folder': row['relative_folder'], 'categorical_compatibility': match['categorical_compatibility'], 'unresolved_reason': match['reason'], 'native_mri_scc_path': str(Path(scc_workspace) / 'staging' / report['selection']['relative_folder'] / 'image.nii.gz'), 'source_prediction_scc_path': match['source_prediction_path'], 'source_prediction_relative_path': str(Path(match['source_prediction_path']).relative_to(Path(version['source_versions']['mask_index']['path']).parent)), 'source_foreground_voxels': int(match['mask_voxels']), 'source_label_volumes_mm3': {'1': optional_number(match['vol_med_mm3']), '2': optional_number(match['vol_lat_mm3'])}, 'context': context})
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('package', 'inventory', 'version-record', 'native-reports', 'scc-workspace', 'output'):
        p.add_argument('--' + field, required=True, type=Path)
    a = p.parse_args()
    result = build(a.package, a.inventory, a.version_record, a.native_reports, a.scc_workspace)
    with a.output.open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False); f.write('\n')
    a.output.chmod(0o600)
    print(json.dumps({'private_contexts': len(result)}))
