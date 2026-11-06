import csv
import json
from pathlib import Path
import pytest
from package_layout import canonical_relative_folder,verify_relative_folder,checked_case_contents
from assemble_and_check_package import validate_catalog_paths
from list_verified_transfer_files import verified_transfer_files


def meta(key='SYNTHETIC_A',month=0,side='L'):
    return dict(participant_id=key,visit_month=month,knee_side=side,source_series_key='SYNTHETIC_SOURCE_'+key,case_key=key)


def make_case(root,m,layout,annotations=False):
    relative=canonical_relative_folder(m,layout)
    folder=root/relative;folder.mkdir(parents=True)
    (folder/'case.json').write_text(json.dumps(dict(m,image_sha256='SYNTHETIC_HASH')))
    (folder/'image.nii.gz').write_bytes(b'not_an_mri_synthetic_list_fixture')
    (folder/'slice_review.csv').write_text('slice_index,status\n0,not_reviewed\n')
    if annotations:(folder/'annotations').mkdir()
    return relative,folder


@pytest.mark.parametrize('layout',['flat','legacy'])
@pytest.mark.parametrize('month,side',[(0,'L'),(72,'R'),(96,'L')])
def test_canonical_identity_each_layout(layout,month,side):
    m=meta(month=month,side=side);relative=canonical_relative_folder(m,layout)
    assert verify_relative_folder(relative,m)==layout
    for field,value in [('participant_id','SYNTHETIC_WRONG'),('visit_month',12),('knee_side','R' if side=='L' else 'L')]:
        changed=dict(m,**{field:value})
        with pytest.raises(ValueError):verify_relative_folder(relative,changed)


@pytest.mark.parametrize('relative',['../elsewhere','/Cases/X','Cases/../X','Cases\\X','Cases//X','Cases/./X','C:/Cases/X'])
def test_unsafe_paths_rejected(relative):
    with pytest.raises(ValueError):verify_relative_folder(relative,meta())


@pytest.mark.parametrize('layout,annotations',[('flat',False),('legacy',False),('legacy',True)])
def test_three_files_and_optional_legacy_empty_placeholder(tmp_path,layout,annotations):
    _,folder=make_case(tmp_path,meta(),layout,annotations)
    assert checked_case_contents(folder,layout)=={'image.nii.gz','case.json','slice_review.csv'}|({'annotations'} if annotations else set())


def test_flat_annotations_directory_rejected(tmp_path):
    _,folder=make_case(tmp_path,meta(),'flat',True)
    with pytest.raises(ValueError,match='unexpected_annotations'):checked_case_contents(folder,'flat')


def test_nonempty_legacy_annotations_preserved_and_rejected(tmp_path):
    _,folder=make_case(tmp_path,meta(),'legacy',True)
    saved=folder/'annotations/SYNTHETIC_DRAFT';saved.write_text('preserve me')
    with pytest.raises(ValueError,match='annotations_not_empty'):checked_case_contents(folder,'legacy')
    assert saved.read_text()=='preserve me'


def test_case_file_symlink_rejected(tmp_path):
    _,folder=make_case(tmp_path,meta(),'flat')
    file=folder/'slice_review.csv';file.unlink();file.symlink_to(folder/'case.json')
    with pytest.raises(ValueError,match='symlink'):checked_case_contents(folder,'flat')


def test_duplicate_case_or_folder_rejected():
    m=meta();c=dict(m,relative_folder=canonical_relative_folder(m))
    with pytest.raises(ValueError,match='duplicate_case_index'):validate_catalog_paths([m],[c,c])
    other=meta('SYNTHETIC_B');other.update(participant_id=m['participant_id'])
    c2=dict(other,relative_folder=canonical_relative_folder(other))
    with pytest.raises(ValueError,match='duplicate_case_folder'):validate_catalog_paths([m,other],[c,c2])


def test_mixed_old_new_package_rejected():
    a,b=meta(),meta('SYNTHETIC_B')
    rows=[dict(a,relative_folder=canonical_relative_folder(a,'flat')),dict(b,relative_folder=canonical_relative_folder(b,'legacy'))]
    with pytest.raises(ValueError,match='mixed_case'):validate_catalog_paths([a,b],rows)


def test_legacy_report_reconnects_to_current_flat_index_for_transfer(tmp_path):
    package=tmp_path/'package';reports=tmp_path/'reports';reports.mkdir()
    m=meta();relative,folder=make_case(package,m,'flat')
    with (package/'case_index.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=['case_key','relative_folder']);w.writeheader();w.writerow(dict(case_key=m['case_key'],relative_folder=relative))
    historical=dict(m,relative_folder=canonical_relative_folder(m,'legacy'))
    report=dict(passed=True,selection=historical,saved_volume=dict(image_sha256='SYNTHETIC_HASH'))
    (reports/'synthetic.json').write_text(json.dumps(report))
    listed=verified_transfer_files(package,reports)
    assert listed==[relative+'/'+name for name in ('image.nii.gz','case.json','slice_review.csv')]
    assert all('series_' not in path and 'annotations' not in path for path in listed)
    assert report['selection']['relative_folder']==historical['relative_folder']


def test_future_freeze_uses_flat_paths_and_refuses_historical_overwrite(tmp_path):
    import hashlib
    from make_export_batches import freeze_batches
    selection=tmp_path/'synthetic_selection.csv';technical=tmp_path/'synthetic_technical.csv'
    rows=[]
    for k in range(250):
        row=meta('SYNTHETIC_%03d'%k)
        row.update(native_slices_recorded='7',native_rows_recorded='8',native_columns_recorded='9',archive_visit_folder='SYNTHETIC_VISIT',dataset_role_working='training',practice_reserved='true' if k<6 else 'false')
        rows.append(row)
    with selection.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with technical.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['case_key']);writer.writeheader();writer.writerows({'case_key':r['case_key']} for r in rows[:6])
    workspace=tmp_path/'workspace'
    record=freeze_batches(workspace,selection,technical,'SYNTHETIC_DATASET')
    assert record['folder_layout']=='flat'
    assert record['selection_sha256']==hashlib.sha256(selection.read_bytes()).hexdigest()
    first=(workspace/'private/batch_development.json').read_bytes()
    generated=json.loads(first)+json.loads((workspace/'private/batch_remaining.json').read_text())
    assert {row['case_key'] for row in generated}=={row['case_key'] for row in rows}
    assert all(verify_relative_folder(row['relative_folder'],row)=='flat' for row in generated)
    with pytest.raises(FileExistsError):freeze_batches(workspace,selection,technical,'SYNTHETIC_DATASET')
    assert (workspace/'private/batch_development.json').read_bytes()==first
