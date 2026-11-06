"""Synthetic technical tests. These do not establish anatomical or Windows validity."""
import csv
import errno
import json
from pathlib import Path
import shutil
import sys
import zipfile

import nibabel as nib
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import Dataset, WorkStore, ValidationError, export_approved, sha256
from MeniscusAnnotatorLib import core
from tools.make_synthetic import make_synthetic


@pytest.fixture
def setup(tmp_path):
    source = make_synthetic(tmp_path / 'Source données with spaces')
    ds = Dataset(source)
    store = WorkStore(tmp_path / 'Local travail 工作', ds)
    return source, ds, store


def seg_writer(path):
    # Persistence fault tests use this marker; real Slicer tests use actual .seg.nrrd.
    path.write_bytes(b'SYNTHETIC TEST WRITER; NOT A SLICER SEGMENTATION')
    return True


def finish_review(session):
    for review in session.state['review']:
        review['reviewed'] = True
    session.state['compartments'] = {'medial': True, 'lateral': True}


def refresh_source_index(source, folder):
    m = json.loads((folder / 'case.json').read_text())
    m['image_sha256'] = sha256(folder / 'image.nii.gz')
    (folder / 'case.json').write_text(json.dumps(m))
    path = source / 'case_index.csv'
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        if row['case_key'] == m['case_key']:
            row['image_sha256'] = m['image_sha256']
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_package_native_axis_and_oblique(setup):
    source, ds, store = setup
    assert len(ds.cases) == 2
    assert [c.n_slices for c in ds.cases] == [17, 23]
    assert ds.cases[1].shape_xyz == (112, 88, 23)
    for case in ds.cases:
        assert case.affine_ras.shape == (4, 4)
        assert store.summary(case)['status'] == 'not_started'


@pytest.mark.parametrize('case_index', [0, 1])
def test_full_grid_save_reopen_export(setup, tmp_path, case_index):
    source, ds, store = setup
    before = {str(p): sha256(p) for p in source.rglob('*') if p.is_file()}
    case = ds.cases[case_index]
    with store.open_case(case) as session:
        labels, uncertainty, path = session.load()
        assert path is None
        labels[5, 13, 17] = 1
        labels[5, 15, 22] = 2
        finish_review(session)
        session.state['last_slice'] = 5
        checkpoint = session.save(labels, uncertainty, seg_writer, approve=True, practice=True)
    assert store.summary(case)['status'] == 'practice_approved'
    with store.open_case(case) as resumed:
        actual, uncertain, seg = resumed.load()
        assert np.array_equal(actual, labels) and np.array_equal(uncertain, uncertainty)
        assert actual[4].sum() == actual[6].sum() == 0
        assert actual[5, 13, 17] == 1 and actual[5, 15, 22] == 2
        assert resumed.state['last_slice'] == 5 and seg == checkpoint/'segmentation.seg.nrrd'
    with pytest.raises(ValidationError, match='No eligible'):
        export_approved(store, tmp_path / 'Results')
    output = export_approved(store, tmp_path/'Results', [case.key], include_practice=True)
    assert output.name.startswith('PRACTICE_ONLY-')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(name.endswith('/image.nii.gz') for name in archive.namelist())
        manifest = json.loads(archive.read('results.json'))
        assert manifest['practice_only'] and len(manifest['cases']) == 1
    assert before == {str(p): sha256(p) for p in source.rglob('*') if p.is_file()}


def test_prediction_free_never_loads_nearby_mask(setup):
    _, ds, store = setup
    c = ds.cases[0]
    nib.save(nib.Nifti1Image(np.ones(c.shape_xyz, dtype=np.uint8), c.affine_ras), c.folder/'prediction.nii.gz')
    with store.open_case(c) as session:
        labels, uncertainty, _ = session.load()
        assert labels.sum() == uncertainty.sum() == 0
        assert session.state['initialization']['method'] == 'blank'


def test_approval_guards_uncertainty_and_draft(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty, _ = session.load()
        assert len(session.approval_errors(labels, uncertainty)) >= 3
        finish_review(session)
        with pytest.raises(ValidationError, match='draft'):
            session.save(labels, uncertainty, seg_writer, approve=True)
        uncertainty[3, 2, 1] = 1
        with pytest.raises(ValidationError, match='uncertain'):
            session.save(labels, uncertainty, seg_writer, approve=True, practice=True)
        uncertainty[:] = 0
        session.state['review'][0]['flag'] = True
        assert any('flags' in e for e in session.approval_errors(labels, uncertainty, True))


def test_review_invalidation_approved_version_preserved(setup):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        labels, uncertainty, _ = session.load()
        finish_review(session)
        approved = session.save(labels, uncertainty, seg_writer, approve=True, practice=True)
        approved_hash = sha256(approved / 'manifest.json')
        labels[6, 3, 2] = 1
        session.mark_changed([6])
        assert not session.state['review'][6]['reviewed']
        assert session.state['review'][5]['reviewed']
        assert session.state['approval'] is None
        draft = session.save(labels, uncertainty, seg_writer)
        assert draft != approved and approved_hash == sha256(approved/'manifest.json')
        assert session.state['status'] == 'needs_review'


def test_duplicate_sessions_rejected_and_released(setup):
    _, ds, store = setup
    one = store.open_case(ds.cases[0])
    with pytest.raises(ValidationError, match='another application'):
        store.open_case(ds.cases[0])
    one.close()
    store.open_case(ds.cases[0]).close()


def test_interrupted_save_and_corrupt_latest_recovery(setup):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        labels, uncertainty, _ = session.load()
        first = session.save(labels, uncertainty, seg_writer)
        labels[3, 1, 2] = 2
        def failure(path):
            path.write_bytes(b'partial')
            raise OSError(errno.ENOSPC, 'No space left on device')
        with pytest.raises(ValidationError, match='previous saved version is intact'):
            session.save(labels, uncertainty, failure)
        assert len(store._checkpoints(session.folder)) == 1
        second = session.save(labels, uncertainty, seg_writer)
        (second/'labels.nii.gz').write_bytes(b'corrupt')
        pending = session.folder/'versions'/'.pending-crash'
        pending.mkdir()
    with store.open_case(c) as resumed:
        assert resumed.recovered
        assert resumed.current_checkpoint == first
        assert resumed.load()[0].sum() == 0


@pytest.mark.parametrize('failure', ['qform', 'sform', 'units', 'conflict'])
def test_bad_transforms_or_units_block_import(setup, failure):
    source, ds, _ = setup
    c = ds.cases[0]
    original = nib.load(c.image_path)
    data = np.asanyarray(original.dataobj)
    im = nib.Nifti1Image(data, original.affine)
    im.header.set_xyzt_units('mm')
    im.set_qform(original.affine, 1)
    im.set_sform(original.affine, 1)
    if failure == 'qform': im.set_qform(original.affine, 0)
    if failure == 'sform': im.set_sform(original.affine, 0)
    if failure == 'units': im.header.set_xyzt_units('unknown')
    if failure == 'conflict':
        shifted = original.affine.copy(); shifted[0, 3] += 4
        im.set_sform(shifted, 1)
    nib.save(im, c.image_path)
    refresh_source_index(source, c.folder)
    with pytest.raises(ValidationError): Dataset(source)


def test_wrong_source_rejected_on_resume(setup):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        session.save(*session.blank_arrays(), seg_writer)
    with c.image_path.open('ab') as stream: stream.write(b'changed')
    with pytest.raises(ValidationError, match='checksum changed'):
        store.open_case(c)


@pytest.mark.parametrize('kind', ['crop', 'invalid', 'float', 'uncertainty'])
def test_invalid_label_or_extent_rejected(setup, kind):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        if kind == 'crop': labels = labels[:, :-1]
        if kind == 'invalid': labels[0, 0, 0] = 3
        if kind == 'float': labels = labels.astype(float)
        if kind == 'uncertainty': uncertainty[0, 0, 0] = 2
        with pytest.raises(ValidationError): session.save(labels, uncertainty, seg_writer)


def test_disk_full_and_unwritable_payload_preserve_previous(setup, monkeypatch):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        first = session.save(labels, uncertainty, seg_writer)
        monkeypatch.setattr(core.shutil, 'disk_usage', lambda p: type('Usage', (), {'free': 0})())
        with pytest.raises(ValidationError, match='Insufficient'): session.save(labels, uncertainty, seg_writer)
        assert first.exists() and session.current_checkpoint == first


def test_work_folder_source_protected_and_dataset_binding(setup, tmp_path):
    source, ds, store = setup
    with pytest.raises(ValidationError, match='separate'): WorkStore(source/'work', ds)
    with pytest.raises(ValidationError, match='cloud'): WorkStore(tmp_path/'Dropbox'/'work', ds)
    changed = Dataset(source)
    changed.identity = 'another'
    with pytest.raises(ValidationError, match='different dataset'): WorkStore(store.root, changed)


def test_explicit_verified_correction_preserved(setup, tmp_path):
    _, ds, _ = setup
    c = ds.cases[1]
    labels = np.zeros(c.shape_xyz[::-1], dtype=np.uint8); labels[7, 12, 15] = 2
    path = tmp_path/'explicit-start.nii.gz'
    core.write_native(path, labels, c)
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': ds.identity, 'protocol': {'version': 'test-released-1', 'status': 'released'},
           'cases': {c.key: {'annotation_mode': 'correction', 'starting_mask': {'path': str(path), 'source': 'SYNTHETIC phantom', 'version': '1', 'sha256': sha256(path)}}}}
    store = WorkStore(tmp_path/'Correction work', ds, job)
    with store.open_case(c) as session:
        actual, uncertainty, _ = session.load()
        assert np.array_equal(actual, labels)
        assert len(list(session.folder.glob('starting-mask-*.nii.gz'))) == 1
        finish_review(session)
        checkpoint = session.save(actual, uncertainty, seg_writer, approve=True)
        assert session.state['status'] == 'approved'
        assert session.state['initialization']['starting_mask']['version'] == '1'
    output = export_approved(store, tmp_path/'Research results')
    with zipfile.ZipFile(output) as archive:
        assert any(n.endswith('/original-starting-mask.nii.gz') for n in archive.namelist())


def test_validity_does_not_silently_confirm_background(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        session.state['review'][2]['reviewed'] = True
        session.state['review'][3].update(reviewed=True, flag=True)
        uncertainty[2, 4, 5] = 1
        checkpoint = session.save(labels, uncertainty, seg_writer)
        validity = np.asanyarray(nib.load(checkpoint/'validity.nii.gz').dataobj).transpose(2, 1, 0)
        assert validity[0].sum() == validity[3].sum() == 0
        assert validity[2, 4, 5] == 0
        assert validity[2].sum() == labels.shape[1]*labels.shape[2]-1


def test_permission_failure_leaves_previous_checkpoint(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        first = session.save(labels, uncertainty, seg_writer)
        def failure(path): raise PermissionError(errno.EACCES, 'Permission denied')
        with pytest.raises(ValidationError, match='write permission'):
            session.save(labels, uncertainty, failure)
        assert store._validate_checkpoint(first, session.case)[0]['case_key'] == session.case.key


def test_reconnect_same_package_at_new_location(setup, tmp_path):
    source, ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = session.blank_arrays()
        labels[8, 6, 7] = 1
        session.save(labels, uncertainty, seg_writer)
    moved = tmp_path/'Reconnected données'
    shutil.copytree(source, moved)
    reconnected = Dataset(moved)
    assert reconnected.identity == ds.identity
    store2 = WorkStore(store.root, reconnected)
    with store2.open_case(reconnected.cases[0]) as session:
        assert session.load()[0][8, 6, 7] == 1


def test_corrupt_all_saved_versions_blocks_case(setup):
    _, ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        checkpoint = session.save(*session.blank_arrays(), seg_writer)
    (checkpoint/'annotation.json').write_text('broken')
    with pytest.raises(ValidationError, match='No intact saved version'):
        store.open_case(case)


def test_missing_slice_review_blocks_dataset(setup):
    source, ds, _ = setup
    path = ds.cases[0].folder/'slice_review.csv'
    path.write_text('slice_index,status\n0,not_reviewed\n')
    with pytest.raises(ValidationError, match='incomplete'): Dataset(source)


def test_catalog_path_escape_blocks_dataset(setup):
    source, ds, _ = setup
    path = source/'case_index.csv'
    value = path.read_text()
    value = value.replace('Cases/OAI_SYNTHETIC_01/M000/LEFT/series_SYNTHETIC_01', '../elsewhere')
    path.write_text(value)
    with pytest.raises(ValidationError, match='unsafe'): Dataset(source)


@pytest.mark.parametrize('name', ['case.json', 'slice_review.csv', 'case_index.csv'])
def test_source_metadata_changes_block_open_and_save(setup, name):
    source, ds, store = setup
    case = ds.cases[0]
    path = source/name if name == 'case_index.csv' else case.folder/name
    with store.open_case(case) as session:
        path.write_bytes(path.read_bytes() + b'\n')
        with pytest.raises(ValidationError, match='source metadata'):
            session.save(*session.blank_arrays(), seg_writer)
    with pytest.raises(ValidationError, match='source metadata'):
        store.open_case(case)


def test_export_whitelist_excludes_stray_private_file(setup, tmp_path):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        finish_review(session)
        checkpoint = session.save(labels, uncertainty, seg_writer, approve=True, practice=True)
    (checkpoint/'DO_NOT_EXPORT_PRIVATE.txt').write_text('SYNTHETIC PRIVATE MARKER')
    output = export_approved(store, tmp_path/'Results', include_practice=True)
    with zipfile.ZipFile(output) as archive:
        assert not any('PRIVATE' in name for name in archive.namelist())


def test_protocol_cannot_be_self_promoted_without_explicit_job(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = session.blank_arrays()
        finish_review(session)
        session.state['protocol'] = {'version': 'invented', 'status': 'released'}
        with pytest.raises(ValidationError, match='explicit job configuration'):
            session.save(labels, uncertainty, seg_writer, approve=True)


def test_changed_prediction_permission_blocks_saved_correction(setup, tmp_path):
    _, ds, _ = setup
    case = ds.cases[0]
    start = tmp_path/'start.nii.gz'
    core.write_native(start, np.zeros(case.shape_xyz[::-1], dtype=np.uint8), case)
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': ds.identity, 'cases': {case.key: {'annotation_mode': 'correction', 'starting_mask': {'path': str(start), 'source': 'SYNTHETIC', 'version': '1', 'sha256': sha256(start)}}}}
    location = tmp_path/'Correction local'
    with WorkStore(location, ds, job).open_case(case) as session:
        labels, uncertainty, _ = session.load()
        session.save(labels, uncertainty, seg_writer)
    blank_store = WorkStore(location, ds)
    with pytest.raises(ValidationError, match='initialization permissions'):
        blank_store.open_case(case)


def test_lock_released_after_abrupt_process_exit(setup):
    import subprocess
    _, ds, store = setup
    repo = str(Path(__file__).resolve().parents[1])
    script = "import sys,os;sys.path.insert(0,%r);from MeniscusAnnotatorLib import Dataset,WorkStore;d=Dataset(%r);s=WorkStore(%r,d).open_case(d.cases[0]);os._exit(17)" % (repo, str(ds.root), str(store.root))
    result = subprocess.run([sys.executable, '-c', script], capture_output=True)
    assert result.returncode == 17, result.stderr.decode()
    store.open_case(ds.cases[0]).close()
