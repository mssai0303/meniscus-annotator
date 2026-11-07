"""Private exact-acquisition inventory for the frozen whole-OAI v1 predictions.

Metadata and checksums only. No image conversion, model execution or selection.
Run on SCC; output contains participant identities and must stay outside Git.
"""
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from source_operation_gate import require_source_permission


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            value.update(chunk)
    return value.hexdigest()


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def indexed(rows, fields):
    result = collections.defaultdict(list)
    for row in rows:
        result[tuple(row[k] for k in fields)].append(row)
    return result


def integer(value):
    return int(float(value))


def build_inventory(workspace, release, pipeline, output, checkpoint, expected_count=250):
    selected_path = workspace / 'private/PRIVATE_selected_250_clinically_corrected.csv'
    selected = read_csv(selected_path)
    require_source_permission(workspace, selected)
    if len(selected) != expected_count or len({r['participant_id'] for r in selected}) != expected_count:
        raise ValueError('fixed_selection_cardinality_mismatch')
    series_path = release / 'data/meniscus_series.csv'
    mask_index_path = release / 'masks/masks_index.csv'
    manifest = {}
    for line in (release/'CHECKSUMS_sha256.txt').read_text().splitlines():
        fingerprint, separator, relative = line.partition('  ')
        if separator:
            if relative in manifest:
                raise ValueError('duplicate_release_checksum_entry')
            manifest[relative] = fingerprint
    for relative in ('README.txt','data/meniscus_series.csv','masks/masks_index.csv','masks/README.txt','docs/METHODS.txt'):
        if manifest.get(relative) != sha256(release/relative):
            raise ValueError('published_release_metadata_checksum_mismatch')
    series = indexed(read_csv(series_path), ('visit_folder', 'participant', 'study_date', 'series'))
    mask_index = indexed(read_csv(mask_index_path), ('row',))
    gate_path = pipeline / 'run/private/dry/PRIVATE_dry_gate.json'
    gate = json.loads(gate_path.read_text())
    expected_model = gate['model_sha256']
    checkpoint = Path(checkpoint)
    actual_model = sha256(checkpoint) if checkpoint.is_file() else None
    source_hashes = {}
    for name in ('regen_common.py', 'regen_stage_a.py', 'regen_stage_b.py', 'regen_stage_c.py', 'regen_split.py', 'regen_merge.py'):
        path = pipeline / 'source' / name
        actual = sha256(path)
        source_hashes[name] = {'path': str(path), 'sha256': actual, 'frozen_gate_sha256': gate['fingerprints'][name], 'matches_frozen_gate': actual == gate['fingerprints'][name]}
    package_hashes = {}
    for name in ('build_package.py', 'nifti_writer.py'):
        path = pipeline / 'package_v1/source' / name
        package_hashes[name] = {'path': str(path), 'sha256': sha256(path)}
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    result, original_rows = [], []
    done_cache = {}
    for scan in selected:
        identity = tuple(scan[k] for k in ('archive_visit_folder', 'participant_id', 'study_date', 'archive_series_number'))
        item = {'case_key': scan['case_key'], 'participant_id': scan['participant_id'], 'visit_month': scan['visit_month'], 'knee_side': scan['knee_side'], 'source_series_key': scan['source_series_key'], 'archive_visit_folder': scan['archive_visit_folder'], 'study_date': scan['study_date'], 'archive_series_number': scan['archive_series_number'], 'source_inventory_row': scan['source_inventory_row'], 'match_status': 'missing', 'categorical_compatibility': 'unresolved', 'reason': '', 'release_version': 'OAI_meniscus_v1_2026-10-22', 'pipeline_method': 'meniscus_regen_v1; frozen model; V20 split', 'model_sha256': expected_model, 'source_prediction_path': '', 'source_prediction_sha256': '', 'source_prediction_bytes': '', 'pipeline_status': '', 'split_method': '', 'split_cut_plane': '', 'medial_is_low_index': '', 'x_low_index_mm': '', 'x_high_index_mm': '', 'mask_voxels': '', 'vol_med_mm3': '', 'vol_lat_mm3': '', 'iso_nx': '', 'iso_ny': '', 'iso_nz': '', 'run_masks_npz_path': '', 'run_masks_npz_expected_sha256': '', 'run_done_path': '', 'run_done_sha256': '', 'pipeline_model_fingerprint_verified': False, 'native_series_instance_uid': '', 'native_image_sha256': '', 'pipeline_dicom_uid_recorded': False, 'exact_acquisition_match_basis': 'archive visit+participant+study date+series; immutable inventory row; actual month and side; native source record', 'native_geometry_metadata_matches': False}
        matches = series.get(identity, [])
        if not matches:
            item['reason'] = 'exact_archive_acquisition_not_in_frozen_release'
            result.append(item); continue
        if len(matches) != 1:
            item.update(match_status='ambiguous', reason='multiple_release_rows_for_exact_archive_acquisition')
            result.append(item); continue
        row = matches[0]
        if any(str(row[k]) != str(scan[v]) for k,v in [('month','visit_month'),('side','knee_side'),('row','source_inventory_row')]):
            item.update(match_status='incompatible', reason='release_identity_or_inventory_row_disagrees')
            result.append(item); continue
        # The preparation source key was defined over these exact four archive components.
        if hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest() != scan['source_series_key']:
            raise ValueError('fixed_source_key_does_not_match_archive_identity')
        entries = mask_index.get((row['row'],), [])
        if len(entries) != 1:
            item.update(match_status='ambiguous' if entries else 'missing', reason='prediction_index_row_not_unique_or_missing')
            result.append(item); continue
        mask = entries[0]
        if any(mask[k] != row[k] for k in ('row','participant','month','side','series')):
            item.update(match_status='incompatible', reason='mask_index_identity_disagrees_with_release_series')
            result.append(item); continue
        relative = PurePosixPath(mask['file'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in mask['file']:
            raise ValueError('unsafe_prediction_index_path')
        prediction = release / 'masks' / relative
        item.update(source_prediction_path=str(prediction), source_prediction_sha256=mask['file_sha256'])
        if manifest.get('masks/'+mask['file']) != mask['file_sha256']:
            item.update(match_status='incompatible', reason='mask_index_disagrees_with_published_release_checksum_manifest')
            result.append(item); continue
        if not prediction.is_file() or prediction.is_symlink():
            item.update(reason='indexed_prediction_file_missing_or_symlink')
            result.append(item); continue
        if sha256(prediction) != mask['file_sha256']:
            item.update(match_status='incompatible', reason='prediction_checksum_differs_from_frozen_index')
            result.append(item); continue
        native_report_path = workspace / 'private/verification' / (scan['case_key'] + '.json')
        native = json.loads(native_report_path.read_text())
        if not native.get('passed') or native['selection']['source_series_key'] != scan['source_series_key']:
            raise ValueError('native_mri_source_verification_missing_or_disagrees')
        for field in ('participant_id','study_date','archive_series_number','archive_visit_folder','knee_side','visit_month'):
            if str(native['selection'][field]) != str(scan[field]):
                raise ValueError('native_verified_source_binding_disagrees')
        first = native['source']['source_files'][0]
        iop = first['orientation_lps']
        normal = [iop[1]*iop[5]-iop[2]*iop[4], iop[2]*iop[3]-iop[0]*iop[5], iop[0]*iop[4]-iop[1]*iop[3]]
        metadata_matches = all(integer(row[a]) == integer(scan[b]) for a,b in [('native_nx','native_columns_recorded'),('native_ny','native_rows_recorded'),('n_slices','native_slices_recorded'),('n_files_index','native_slices_recorded')])
        metadata_matches &= integer(row['n_gdcm_ids']) == 1 and integer(row['n_read']) == integer(scan['native_slices_recorded'])
        metadata_matches &= integer(row['n_files']) == integer(scan['native_slices_recorded']) and str(row['spacing_repaired']).lower() in ('0','false')
        for field, values in [('rowdir',iop[:3]),('coldir',iop[3:]),('normal',normal)]:
            metadata_matches &= all(abs(float(row[field+'_'+axis])-float(value)) <= 1e-5 for axis,value in zip('xyz',values))
        metadata_matches &= all(abs(float(row[a])-float(scan[b])) <= 1e-5 for a,b in [('spacing_x','spacing_x_recorded_mm'),('spacing_y','spacing_y_recorded_mm'),('spacing_z','slice_step_recorded_mm')])
        if not metadata_matches:
            item.update(match_status='incompatible', reason='release_native_geometry_metadata_disagrees')
            result.append(item); continue
        part, chunk, sub = [integer(scan[k]) for k in ('archive_part','archive_chunk','archive_subfolder')]
        chunk_folder = pipeline / 'run/private/out' / ('part%d' % part) / ('chunk_%d' % chunk)
        done_path = chunk_folder / ('sb%d_done.json' % sub)
        npz_path = chunk_folder / ('sb%d_masks.npz' % sub)
        if str(done_path) not in done_cache:
            done_cache[str(done_path)] = json.loads(done_path.read_text())
        done = done_cache[str(done_path)]
        recorded_model = done['stage_b']['runtime']['model_sha256']
        if integer(row['row']) not in done['rows'] or recorded_model != expected_model:
            item.update(match_status='incompatible', reason='run_membership_or_model_fingerprint_disagrees')
            result.append(item); continue
        if any(integer(mask[k]) != integer(row[k]) for k in ('iso_nx','iso_ny','iso_nz')):
            item.update(match_status='incompatible', reason='mask_index_grid_disagrees_with_release_series')
            result.append(item); continue
        item.update(match_status='matched', native_geometry_metadata_matches=True, pipeline_status=row['status'], source_prediction_bytes=prediction.stat().st_size, native_series_instance_uid=native['source']['series_instance_uid'], native_image_sha256=native['saved_volume']['image_sha256'], run_masks_npz_path=str(npz_path), run_masks_npz_expected_sha256=done['files']['masks'], run_done_path=str(done_path), run_done_sha256=sha256(done_path), pipeline_model_fingerprint_verified=True)
        for field in ('split_method','split_cut_plane','medial_is_low_index','x_low_index_mm','x_high_index_mm','mask_voxels','vol_med_mm3','vol_lat_mm3','iso_nx','iso_ny','iso_nz'):
            item[field] = row.get(field, mask.get(field,''))
        # mask_voxels is the published binary-mask voxel count, not a quality screen.
        item['mask_voxels'] = mask['mask_voxels']
        if row['status'] == 'ok_split' and row['split'] == '1' and row['split_cut_plane'] and row['medial_is_low_index'] in ('0','1'):
            item.update(categorical_compatibility='documented_medial_lateral_assignment', reason='')
        else:
            item.update(reason='existing_pipeline_left_binary_prediction_unsplit_no_medial_lateral_assignment')
        original_rows.append({'case_key':scan['case_key'],'source_series_row':row,'source_mask_index_row':mask})
        result.append(item)
    fields = list(result[0])
    temporary=output/'PRIVATE_prediction_matching_inventory.csv.tmp'
    with temporary.open('w',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(result)
    os.replace(temporary,output/'PRIVATE_prediction_matching_inventory.csv')
    temporary=output/'PRIVATE_original_matched_rows.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(row,sort_keys=True)+'\n' for row in original_rows))
    os.replace(temporary,output/'PRIVATE_original_matched_rows.jsonl')
    sources = {'selection':selected_path,'release_series':series_path,'mask_index':mask_index_path,'pipeline_gate':gate_path,'release_readme':release/'README.txt','masks_readme':release/'masks/README.txt','methods':release/'docs/METHODS.txt','full_release_checksums':release/'CHECKSUMS_sha256.txt'}
    version = {'release_version':'OAI_meniscus_v1_2026-10-22','pipeline_version':'meniscus_regen_v1 frozen source; V20 compartment split','model_path':str(checkpoint),'recorded_inference_model_sha256':expected_model,'current_model_sha256':actual_model,'current_model_matches_inference':actual_model==expected_model,'matching_tool_sha256':sha256(Path(__file__)),'source_versions':{key:{'path':str(value),'sha256':sha256(value)} for key,value in sources.items()},'pipeline_source':source_hashes,'package_writer_source':package_hashes,'matching_counts':dict(collections.Counter(row['match_status'] for row in result)),'categorical_compatibility_counts':dict(collections.Counter(row['categorical_compatibility'] for row in result)),'split_methods':dict(collections.Counter(row['split_method'] for row in result if row['match_status']=='matched')),'selected_prediction_total_compressed_bytes':sum(int(row['source_prediction_bytes'] or 0) for row in result),'source_grid':'binary uint8 NIfTI-1, 0.5mm isotropic, pipeline scanner coordinates; must be checked against each native MRI','label_assignment':'Existing split_cut_plane along physical source-mask array axis0; planes<cut are low, >=cut high. Existing medial_is_low_index selects label1 compartment. Right medial is largerLPSx, left medial smallerLPSx. No new partition.','limits':'Metadata/checksum match and documented split only. Grid resampling and overlay suitability remain separate required checks. Pipeline did not retain DICOM UID in released table; native UID is retained from verified original MRI source.'}
    version['published_release_metadata_checksums_verified']=True
    temporary=output/'prediction_version_and_matching.json.tmp';temporary.write_text(json.dumps(version,indent=2)+'\n')
    os.replace(temporary,output/'prediction_version_and_matching.json')
    for path in output.iterdir():
        if path.is_file():path.chmod(0o600)
    return version


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('workspace','release','pipeline','output','model-checkpoint'):parser.add_argument('--'+field,required=True,type=Path)
    args=parser.parse_args()
    result=build_inventory(args.workspace,args.release,args.pipeline,args.output,args.model_checkpoint)
    print(json.dumps({key:result[key] for key in ('release_version','matching_counts','categorical_compatibility_counts','split_methods','selected_prediction_total_compressed_bytes','current_model_matches_inference')}))
