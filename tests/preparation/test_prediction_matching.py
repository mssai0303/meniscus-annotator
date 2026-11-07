"""Synthetic metadata/checksum tests; these do not validate image alignment."""
import csv
import hashlib
import json
from pathlib import Path

import pytest

import match_existing_predictions as matcher


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, list(rows[0]));writer.writeheader();writer.writerows(rows)


@pytest.fixture
def source(tmp_path, monkeypatch):
    workspace, release, pipeline, output = [tmp_path / name for name in ('workspace','release','pipeline','output')]
    monkeypatch.setattr(matcher, 'require_source_permission', lambda root, rows: None)
    checkpoint = tmp_path / 'SYNTHETIC_MODEL'
    checkpoint.write_bytes(b'SYNTHETIC MODEL FIXTURE; NOT A TRAINED MODEL')
    model_sha = matcher.sha256(checkpoint)
    fingerprints = {}
    for name in ('regen_common.py','regen_stage_a.py','regen_stage_b.py','regen_stage_c.py','regen_split.py','regen_merge.py'):
        p=pipeline/'source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('SYNTHETIC SOURCE '+name);fingerprints[name]=matcher.sha256(p)
    for name in ('build_package.py','nifti_writer.py'):
        p=pipeline/'package_v1/source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('SYNTHETIC WRITER '+name)
    gate=pipeline/'run/private/dry/PRIVATE_dry_gate.json';gate.parent.mkdir(parents=True);gate.write_text(json.dumps({'model_sha256':model_sha,'fingerprints':fingerprints}))
    for relative in ('README.txt','masks/README.txt','docs/METHODS.txt','CHECKSUMS_sha256.txt'):
        p=release/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('SYNTHETIC METADATA FIXTURE')
    selected=[];series=[];masks=[];done_paths=[]
    for i,month in enumerate((0,72),1):
        visit='SYNTHETIC_VISIT_'+str(month);pid='SYNTHETIC_'+str(i);date='SYNTHETIC_DATE';number='SYNTHETIC_SERIES_'+str(i);side='L' if i==1 else 'R'
        key=(visit,pid,date,number);source_key=hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
        scan={'case_key':'SYNTHETIC_CASE_'+str(i),'participant_id':pid,'visit_month':str(month),'knee_side':side,'source_series_key':source_key,'archive_visit_folder':visit,'study_date':date,'archive_series_number':number,'source_inventory_row':str(i),'native_columns_recorded':'16','native_rows_recorded':'12','native_slices_recorded':'3','spacing_x_recorded_mm':'0.4','spacing_y_recorded_mm':'0.5','slice_step_recorded_mm':'3','archive_part':'1','archive_chunk':'1','archive_subfolder':str(i)}
        selected.append(scan)
        row={'visit_folder':visit,'participant':pid,'study_date':date,'series':number,'row':str(i),'month':str(month),'side':side,'native_nx':'16','native_ny':'12','n_slices':'3','n_files_index':'3','n_gdcm_ids':'1','n_read':'3','n_files':'3','spacing_repaired':'0','spacing_x':'0.4','spacing_y':'0.5','spacing_z':'3','rowdir_x':'0','rowdir_y':'1','rowdir_z':'0','coldir_x':'0','coldir_y':'0','coldir_z':'1','normal_x':'1','normal_y':'0','normal_z':'0','iso_nx':'13','iso_ny':'12','iso_nz':'18','status':'ok_split','split':'1','split_method':'april','split_cut_plane':'9','medial_is_low_index':'1' if side=='L' else '0','x_low_index_mm':'10','x_high_index_mm':'15','vol_med_mm3':'1.5','vol_lat_mm3':'1.5'}
        series.append(row)
        relative='SYNTHETIC_MASK_'+str(i)+'.nii.gz';p=release/'masks'/relative;p.write_bytes(b'SYNTHETIC BYTE FIXTURE, NOT A NIFTI')
        masks.append({'row':str(i),'participant':pid,'month':str(month),'side':side,'series':number,'file':relative,'file_sha256':matcher.sha256(p),'iso_nx':'13','iso_ny':'12','iso_nz':'18','mask_voxels':'24'})
        done=pipeline/'run/private/out/part1/chunk_1'/('sb%d_done.json'%i);done.parent.mkdir(parents=True,exist_ok=True);done.write_text(json.dumps({'stage_b':{'runtime':{'model_sha256':model_sha}},'rows':[i],'files':{'masks':'a'*64}}));done_paths.append(done)
        p=workspace/'private/verification'/(scan['case_key']+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'passed':True,'selection':scan,'source':{'series_instance_uid':'SYNTHETIC_UID_'+str(i),'source_files':[{'orientation_lps':[0,1,0,0,0,1]}]},'saved_volume':{'image_sha256':'b'*64}}))
    def save():
        write_csv(workspace/'private/PRIVATE_selected_250_clinically_corrected.csv',selected)
        write_csv(release/'data/meniscus_series.csv',series)
        write_csv(release/'masks/masks_index.csv',masks)
        entries={relative:matcher.sha256(release/relative) for relative in ('README.txt','data/meniscus_series.csv','masks/masks_index.csv','masks/README.txt','docs/METHODS.txt')}
        entries.update({'masks/'+row['file']:row['file_sha256'] for row in masks})
        (release/'CHECKSUMS_sha256.txt').write_text(''.join(h+'  '+p+'\n' for p,h in entries.items()))
    def run():
        save()
        version=matcher.build_inventory(workspace,release,pipeline,output,checkpoint,expected_count=2)
        return version,matcher.read_csv(output/'PRIVATE_prediction_matching_inventory.csv')
    return {'run':run,'selected':selected,'series':series,'masks':masks,'done':done_paths,'release':release,'arguments':(workspace,release,pipeline,output,checkpoint)}


def test_exact_baseline_and_later_acquisition_metadata(source):
    version, rows=source['run']()
    assert version['matching_counts']=={'matched':2}
    assert version['categorical_compatibility_counts']=={'documented_medial_lateral_assignment':2}
    assert all(row['native_series_instance_uid'].startswith('SYNTHETIC_UID') for row in rows)
    assert not any(row['pipeline_dicom_uid_recorded']=='True' for row in rows)


def test_other_acquisition_of_same_knee_visit_is_not_used(source):
    other=dict(source['series'][0],series='SYNTHETIC_OTHER_SERIES',row='99')
    source['series'].append(other)
    version,rows=source['run']()
    assert version['matching_counts']=={'matched':2} and rows[0]['archive_series_number']!='SYNTHETIC_OTHER_SERIES'


def test_exact_duplicate_acquisition_is_ambiguous(source):
    source['series'].append(dict(source['series'][0]))
    version,rows=source['run']()
    assert rows[0]['match_status']=='ambiguous'


def test_wrong_side_is_incompatible(source):
    source['series'][0]['side']='R'
    _,rows=source['run']()
    assert rows[0]['match_status']=='incompatible'


def test_missing_prediction_file_remains_missing(source):
    (source['release']/'masks'/source['masks'][0]['file']).unlink()
    _,rows=source['run']()
    assert rows[0]['match_status']=='missing'


def test_changed_prediction_bytes_are_rejected(source):
    (source['release']/'masks'/source['masks'][0]['file']).write_bytes(b'CHANGED SYNTHETIC BYTES')
    _,rows=source['run']()
    assert rows[0]['match_status']=='incompatible' and 'checksum' in rows[0]['reason']


def test_unsplit_source_is_matched_but_not_fabricated_as_categorical(source):
    source['series'][0].update(status='ok_whole',split='0',split_method='whole',split_cut_plane='',medial_is_low_index='')
    version,rows=source['run']()
    assert version['matching_counts']=={'matched':2}
    assert rows[0]['categorical_compatibility']=='unresolved'
    assert 'unsplit' in rows[0]['reason']


def test_different_recorded_model_is_not_mixed(source):
    p=source['done'][0];d=json.loads(p.read_text());d['stage_b']['runtime']['model_sha256']='c'*64;p.write_text(json.dumps(d))
    _,rows=source['run']()
    assert rows[0]['match_status']=='incompatible' and 'model' in rows[0]['reason']


def test_different_native_geometry_is_incompatible(source):
    source['series'][0]['normal_x']='-1'
    _,rows=source['run']()
    assert rows[0]['match_status']=='incompatible' and 'geometry' in rows[0]['reason']


def test_published_metadata_checksum_is_required(source):
    source['run']()
    table=source['release']/'data/meniscus_series.csv'
    table.write_bytes(table.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='published_release_metadata_checksum'):
        matcher.build_inventory(*source['arguments'],expected_count=2)
