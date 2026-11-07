"""Frozen-acquisition joins and byte-preserving resume, without inference."""
import csv
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from make_synthetic import make_synthetic
from build_correction_contexts import build, optional_number
import run_starting_mask_batch as batch


def context_fixture(tmp_path):
    package = make_synthetic(tmp_path / 'source', layout='flat')
    with (package / 'case_index.csv').open(newline='') as f:
        catalog = list(csv.DictReader(f))
    reports = tmp_path / 'reports';reports.mkdir()
    mask_root = tmp_path / 'masks';mask_root.mkdir()
    rows = []
    for i, row in enumerate(catalog):
        m = json.loads((package / row['relative_folder'] / 'case.json').read_text())
        report = {'selection': {'source_series_key': m['source_series_key'], 'relative_folder': row['relative_folder']}, 'saved_volume': {'image_sha256': m['image_sha256']}}
        (reports / (m['case_key'] + '.json')).write_text(json.dumps(report))
        rows.append(dict(case_key=m['case_key'], participant_id=m['participant_id'], knee_side=m['knee_side'], source_series_key=m['source_series_key'], visit_month='0', native_image_sha256=m['image_sha256'], native_series_instance_uid=m['series_instance_uid'], match_status='matched', source_inventory_row=str(i), archive_visit_folder='SYNTHETIC', study_date='SYNTHETIC', archive_series_number=str(i), iso_nx='5', iso_ny='6', iso_nz='7', source_prediction_sha256='b'*64, split_cut_plane='3', medial_is_low_index='1', split_method='april', x_low_index_mm='3', x_high_index_mm='4', source_prediction_path=str(mask_root / ('synthetic%d.nii.gz' % i)), categorical_compatibility='documented_medial_lateral_assignment', reason='', mask_voxels='5', vol_med_mm3='.25', vol_lat_mm3='.375'))
    inventory = tmp_path / 'matches.csv'
    def write():
        with inventory.open('w', newline='') as f:
            w = csv.DictWriter(f, list(rows[0]));w.writeheader();w.writerows(rows)
    write()
    version = tmp_path / 'version.json';version.write_text(json.dumps({'release_version':'SYNTHETIC_RELEASE','pipeline_version':'SYNTHETIC_PIPELINE','recorded_inference_model_sha256':'a'*64,'source_versions':{'mask_index':{'path':str(mask_root/'index.csv')}}}))
    return package, inventory, version, reports, rows, write


def test_contexts_bind_exact_case_series_and_grid_metadata(tmp_path):
    package, inventory, version, reports, rows, _ = context_fixture(tmp_path)
    out = build(package, inventory, version, reports, tmp_path/'remote_workspace')
    assert len(out) == 2 and out[0]['context']['source_series_key'] == rows[0]['source_series_key']
    assert out[0]['context']['source_grid_dimensions_xyz'] == [5,6,7]
    assert optional_number('nan') is None and optional_number('') is None


@pytest.mark.parametrize('field,value', [('native_series_instance_uid','WRONG_SERIES'),('visit_month','72'),('source_series_key','OTHER_ACQUISITION')])
def test_contexts_reject_wrong_acquisition_even_if_participant_matches(tmp_path, field, value):
    package, inventory, version, reports, rows, write = context_fixture(tmp_path)
    rows[0][field] = value;write()
    with pytest.raises(ValueError, match='mismatch'):
        build(package, inventory, version, reports, tmp_path/'remote_workspace')


def resume_fixture(tmp_path):
    key = 'SYNTHETIC_KEY';relative = 'Cases/OAI_SYNTHETIC_M000_LEFT'
    base = tmp_path/'private/correction_preparation_20261106';folder=base/'prepared'/relative;folder.mkdir(parents=True)
    reports=base/'verification';reports.mkdir()
    mri=tmp_path/'source-image';mri.write_bytes(b'SYNTHETIC MRI BYTE TRUST FIXTURE')
    prediction=tmp_path/'original-prediction';prediction.write_bytes(b'SYNTHETIC ORIGINAL PREDICTION')
    mask=folder/'starting_mask.nii.gz';mask.write_bytes(b'SYNTHETIC VERIFIED OUTPUT BYTES')
    context={'image_sha256':batch.sha256(mri),'source_prediction':{'sha256':batch.sha256(prediction)}}
    side={'prepared_mask_sha256':batch.sha256(mask)};(folder/'starting_mask.json').write_text(json.dumps(side))
    report={'passed':True,'source_context':context,'sidecar':side,'source_label_counts':{'1':2,'2':3},'source_label_volumes_mm3':{'1':.25,'2':.375}}
    report_path=reports/(key+'.json');report_path.write_text(json.dumps(report))
    record={'case_key':key,'relative_folder':relative,'context':context,'native_mri_scc_path':str(mri),'source_prediction_scc_path':str(prediction),'source_foreground_voxels':5,'source_label_volumes_mm3':{'1':.25,'2':.375}}
    return record,report_path,mri


def test_resume_does_not_regenerate_existing_verified_mask(tmp_path, monkeypatch):
    record, report, _=resume_fixture(tmp_path);before=report.read_bytes()
    def no_conversion(*args,**kwargs):raise AssertionError('must not regenerate')
    monkeypatch.setattr(batch,'prepare',no_conversion)
    assert batch.one((record,str(tmp_path)))['passed']
    assert report.read_bytes()==before


def test_resume_rejects_changed_original_mri(tmp_path):
    record, _, mri=resume_fixture(tmp_path);mri.write_bytes(b'CHANGED SOURCE')
    result=batch.one((record,str(tmp_path)))
    assert not result['passed'] and result['error']=='resume_MRI_changed'
