"""Synthetic regressions for independent review P1/B1/I3/I11/I13.

The legacy fixture mirrors the preview's absent local reader_assignment field,
while using an explicitly synthetic actor rather than an old hard-coded doctor.
"""
import copy
import json
from pathlib import Path
import sys
import zipfile

import nibabel as nib
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import core, Dataset, WorkStore, ValidationError, export_approved, sha256
from tools.make_synthetic import make_synthetic


@pytest.fixture
def setup(tmp_path):
    ds = Dataset(make_synthetic(tmp_path/'Synthetic inputs'))
    store = WorkStore(tmp_path/'Synthetic reader work', ds, reader='Synthetic Repair Reader')
    return ds, store


def writer(path): path.write_bytes(b'SYNTHETIC persistence marker, not real segmentation')


def arrays(session):
    labels, uncertainty = session.blank_arrays()
    labels[2, 4, 6] = 1
    labels[4, 8, 10] = 2
    return labels, uncertainty


def approve(session, labels, uncertain):
    for row in session.state['review']: row['reviewed'] = True
    session.state['compartments'] = {'medial': True, 'lateral': True}
    return session.save(labels, uncertain, writer, approve=True, practice=True)


def rewrite_manifest(checkpoint, filename):
    manifest = json.loads((checkpoint/'manifest.json').read_text(encoding='utf-8'))
    manifest['files_sha256'][filename] = sha256(checkpoint/filename)
    (checkpoint/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


@pytest.mark.parametrize('default_encoding', ['utf-8', 'cp1252'])
def test_p1_8530_shape_legacy_reader_binding_saves_without_rewriting_old(setup, monkeypatch, default_encoding):
    # Windows CP1252 must not corrupt the UTF-8 source metadata while this test
    # constructs its legacy fixture. Production JSON always uses explicit UTF-8.
    original_read, original_write = Path.read_text, Path.write_text
    def locale_read(path, *args, **kwargs):
        if not args and kwargs.get('encoding') is None:
            kwargs['encoding'] = default_encoding
        return original_read(path, *args, **kwargs)
    def locale_write(path, text, *args, **kwargs):
        if not args and kwargs.get('encoding') is None:
            kwargs['encoding'] = default_encoding
        return original_write(path, text, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', locale_read)
    monkeypatch.setattr(Path, 'write_text', locale_write)
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        old = session.save(labels, uncertainty, writer)
    old_state = json.loads((old/'annotation.json').read_text(encoding='utf-8'))
    old_state.pop('reader_assignment', None) # preview 8530b18 has no local-binding field
    old_state['app_version'] = '0.1.0'
    (old/'annotation.json').write_text(json.dumps(old_state), encoding='utf-8')
    rewrite_manifest(old, 'annotation.json')
    store.reader_assignment_path.unlink()
    before = {p.name: sha256(p) for p in old.iterdir()}
    reopened_store = WorkStore(store.root, ds, reader='Synthetic Repair Reader')
    reopened_store._validate_checkpoint(old, case) # expose fixture errors before recovery's generic message
    with reopened_store.open_case(case) as session:
        regions, regional_uncertain, regional_state = session.load_regions()
        new = session.save(labels, uncertainty, writer, regions=regions, regional_uncertainty=regional_uncertain, regional_state=regional_state)
        assert new != old
        assert session.state['annotator'] == old_state['annotator']
        assert session.state['job_identity'] == old_state['job_identity']
        assert session.regional_state['reader_assignment'] == session.state['reader_assignment']
    assert before == {p.name: sha256(p) for p in old.iterdir()}


def test_i3_unchanged_approved_save_is_idempotent(setup):
    ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = arrays(session)
        approve(session, labels, uncertainty)
        original_approval = copy.deepcopy(session.state['approval'])
        session.state['review'][2]['reviewed'] = True # idempotent UI action
        session.save(labels, uncertainty, writer)
        assert session.state['status'] == 'practice_approved'
        assert session.state['approval'] == original_approval


def test_i13_ordinary_draft_practice_has_no_research_targets(setup):
    ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = arrays(session)
        checkpoint = approve(session, labels, uncertainty)
        assert session.state['annotation_purpose'] == 'protocol_practice'
        assert session.state['approval_purpose'] == 'protocol_practice'
        assert session.state['accepted_research_annotation'] is False
        assert np.asarray(nib.load(checkpoint/'validity.nii.gz').dataobj).all() # review semantics, not research eligibility
        assert not np.asarray(nib.load(checkpoint/'research_eligibility.nii.gz').dataobj).any()
        assert b'PRACTICE' in bytes(nib.load(checkpoint/'labels.nii.gz').header['descrip'])


def test_i3_no_silent_old_approval_export(setup, tmp_path):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        old = approve(session, labels, uncertainty)
        labels[2, 4, 7] = 1
        session.mark_changed([2])
        newer = session.save(labels, uncertainty, writer)
    with pytest.raises(ValidationError, match='newer|Newer|explicit'):
        export_approved(store, tmp_path/'Results', include_practice=True)


def test_b1_practice_only_message_is_actionable(setup, tmp_path):
    ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        approve(session, *arrays(session))
    with pytest.raises(ValidationError, match='Practice results|practice approvals'):
        export_approved(store, tmp_path/'Results')


def test_review_mark_is_idempotent_without_new_checkpoint_or_approval_loss(setup):
    ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        labels, uncertainty = arrays(session)
        approve(session, labels, uncertainty)
        before = copy.deepcopy(session.state)
        count = len(store._checkpoints(session.folder))
        assert session.mark_reviewed(2) is False
        assert session.state == before
        assert len(store._checkpoints(session.folder)) == count


def test_journal_is_durable_metadata_only_and_restores_exact_masks(setup, monkeypatch):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        checkpoint = session.save(labels, uncertainty, writer)
        before = {path.name: sha256(path) for path in checkpoint.iterdir()}
        def no_image_write(*args, **kwargs): raise AssertionError('Review must not rewrite images')
        monkeypatch.setattr(core, 'write_native', no_image_write)
        for k in range(5):
            assert session.mark_reviewed(k)
            target = session.save_review_journal(labels, uncertainty)
            assert target.stat().st_size < 100000
        assert len(store._checkpoints(session.folder)) == 1
        assert len(list(target.parent.glob('r-*.json'))) == 5 # no pruning
        assert before == {path.name: sha256(path) for path in checkpoint.iterdir()}
    with store.open_case(case) as restored:
        assert sum(row['reviewed'] for row in restored.state['review']) == 5
        assert np.array_equal(restored.load()[0], labels)
        assert restored.review_journal_pending and restored.review_journal_record == target.name
        assert not restored.journal_warning
    assert store.summary(case)['reviewed'] == 5


def test_journal_rejects_unsaved_voxels_and_full_save_supersedes_without_pruning(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        assert not session.can_journal_review(labels, uncertainty)
        first = session.save(labels, uncertainty, writer)
        session.mark_reviewed(1)
        journal = session.save_review_journal(labels, uncertainty)
        changed = labels.copy(); changed[2, 4, 7] = 1
        assert not session.can_journal_review(changed, uncertainty)
        with pytest.raises(ValidationError, match='checkpoint'): session.save_review_journal(changed, uncertainty)
        second = session.save(labels, uncertainty, writer)
        assert journal.exists() and not session.review_journal_pending and first.exists()
        journal.write_text('damaged superseded journal')
    with store.open_case(case) as resumed:
        assert resumed.current_checkpoint == second and resumed.state['review'][1]['reviewed']
        assert not resumed.journal_warning # superseded journal cannot poison current work


def test_journal_corruption_falls_back_with_visible_warning(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        session.save(labels, uncertainty, writer)
        session.mark_reviewed(1)
        first = session.save_review_journal(labels, uncertainty)
        session.mark_reviewed(2)
        second = session.save_review_journal(labels, uncertainty)
        second.write_text('interrupted or corrupt')
    with store.open_case(case) as restored:
        assert restored.state['review'][1]['reviewed'] and not restored.state['review'][2]['reviewed']
        assert restored.review_journal_record == first.name
        assert 'damaged' in restored.journal_warning


def test_journal_disk_failure_keeps_prior_review_record(setup, monkeypatch):
    import errno
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        session.save(labels, uncertainty, writer)
        session.mark_reviewed(1)
        first = session.save_review_journal(labels, uncertainty)
        session.mark_reviewed(2)
        def fail(*args): raise OSError(errno.ENOSPC, 'No space left')
        monkeypatch.setattr(core, 'atomic_json', fail)
        with pytest.raises(ValidationError, match='Review could not be saved'): session.save_review_journal(labels, uncertainty)
        assert len(list(first.parent.glob('r-*.json'))) == 1
    with store.open_case(case) as restored:
        assert restored.state['review'][1]['reviewed'] and not restored.state['review'][2]['reviewed']


def test_regional_journal_marks_survive_following_whole_review(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        from MeniscusAnnotatorLib import regions as regional
        regions = regional.initialize(labels)
        region_uncertainty = np.zeros_like(labels)
        region_state = regional.default_state(case.n_slices, session.state)
        session.save(labels, uncertainty, writer, regions=regions, regional_uncertainty=region_uncertainty, regional_state=region_state)
        assert session.mark_reviewed(2, compartment='medial', regional_state=region_state)
        assert not session.mark_reviewed(2, compartment='medial', regional_state=region_state)
        session.save_review_journal(labels, uncertainty, region_state, regions, region_uncertainty)
        session.mark_reviewed(3)
        session.save_review_journal(labels, uncertainty) # must carry previous regional metadata
    with store.open_case(case) as restored:
        assert restored.state['review'][3]['reviewed']
        assert restored.load_regions()[2]['review'][2]['medial_reviewed']


def test_journal_provenance_tamper_is_rejected_even_rehashed(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        session.save(labels, uncertainty, writer)
        session.mark_reviewed(2)
        target = session.save_review_journal(labels, uncertainty)
        record = json.loads(target.read_text())
        record['payload']['primary_state']['source_identity'] = 'different scan'
        record['payload_sha256'] = core.canonical(record['payload'])
        target.write_text(json.dumps(record))
    with store.open_case(case) as restored:
        assert not restored.state['review'][2]['reviewed']
        assert restored.journal_warning and not restored.review_journal_pending


def test_explicit_previous_approval_choice_records_omitted_newer_version(setup, tmp_path):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        old = approve(session, labels, uncertainty)
        labels[2, 4, 7] = 1
        session.mark_changed([2])
        newest = session.save(labels, uncertainty, writer)
    preflight = core.export_plan(store, include_practice=True)
    assert preflight['requires_choice'][0]['latest_checkpoint'] == newest.name
    assert preflight['requires_choice'][0]['approved_checkpoint'] == old.name
    choice = {case.key: old.name}
    selected = core.export_plan(store, include_practice=True, earlier_choices=choice)
    assert selected['included'][0]['earlier_version']
    output = export_approved(store, tmp_path/'Explicit results', include_practice=True, earlier_choices=choice, plan=selected)
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read('results.json'))
        receipt = manifest['cases'][0]
        assert receipt['checkpoint'] == old.name
        assert receipt['export_selection']['latest_checkpoint'] == newest.name
        assert receipt['export_selection']['selection'] == 'explicit_earlier_approval'
        assert manifest['excluded_cases'] # untouched second synthetic case reported honestly


def test_export_plan_token_detects_new_work_after_preflight(setup, tmp_path):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        approve(session, labels, uncertainty)
        plan = core.export_plan(store, include_practice=True)
        session.state['notes'] = 'Newer unapproved note'
        session.save_review_journal(labels, uncertainty)
    with pytest.raises(ValidationError, match='selection changed'):
        export_approved(store, tmp_path/'Stale selection', include_practice=True, plan=plan)
    assert not (tmp_path/'Stale selection').exists()


def test_default_practice_error_creates_no_empty_results_folder(setup, tmp_path):
    ds, store = setup
    with store.open_case(ds.cases[0]) as session: approve(session, *arrays(session))
    destination = tmp_path/'No empty folder'
    with pytest.raises(ValidationError, match='Practice results'): export_approved(store, destination)
    assert not destination.exists()
    plan = core.export_plan(store, case_keys=[ds.cases[0].key])
    assert plan['excluded'][0]['code'] == 'practice_excluded'


@pytest.mark.parametrize('path', ['C:/Users/Synthetic/OneDrive - Hospital/work', '/Users/Synthetic/Library/Mobile Documents/com~apple~CloudDocs/work',
                                 '/Users/Synthetic/Google Drive/work', '/Users/Synthetic/Box/work', r'\\server\share\work'])
def test_work_location_rejects_known_sync_and_network_paths(path):
    assert core.work_location_problem(path)


def test_work_location_rejects_configured_kfm_without_provider_name(monkeypatch, tmp_path):
    root = tmp_path/'Hospital shared documents'
    monkeypatch.setenv('OneDriveCommercial', str(root))
    assert 'configured cloud-sync' in core.work_location_problem(root/'Meniscus work')
    assert core.work_location_problem(tmp_path/'Local data') is None


def test_native_windows_backslash_paths_are_checked():
    assert core.work_location_problem('\\\\server\\share\\work')
    assert core.work_location_problem('C:\\Users\\Synthetic\\OneDrive - Hospital\\work')
    assert core.work_location_problem('C:\\Users\\Synthetic\\Box\\work')


def test_review_journal_survives_abrupt_process_exit(setup):
    import os
    import subprocess
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        session.save(labels, uncertainty, writer)
    script = ('import os,sys;sys.path.insert(0,%r);from MeniscusAnnotatorLib import Dataset,WorkStore;'
              'd=Dataset(%r);w=WorkStore(%r,d,reader="Synthetic Repair Reader");s=w.open_case(d.cases[0]);'
              'a,u,_=s.load();s.mark_reviewed(4);s.save_review_journal(a,u);os._exit(17)') % (str(Path(__file__).resolve().parents[1]), str(ds.root), str(store.root))
    result = subprocess.run([sys.executable, '-c', script], capture_output=True)
    assert result.returncode == 17, result.stderr
    with store.open_case(case) as restored:
        assert restored.state['review'][4]['reviewed']
        assert restored.review_journal_pending
        assert np.array_equal(restored.load()[0], labels)


def test_full_approval_flushes_journal_into_independent_files(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        first = session.save(labels, uncertainty, writer)
        for k in range(case.n_slices): session.mark_reviewed(k)
        session.state['compartments'] = {'medial': True, 'lateral': True}
        journal = session.save_review_journal(labels, uncertainty)
        latest = session.save(labels, uncertainty, writer, approve=True, practice=True)
        assert latest != first and journal.exists()
        assert not session.review_journal_pending
        saved = json.loads((latest/'annotation.json').read_text())
        assert all(row['reviewed'] for row in saved['review'])
        assert np.asarray(nib.load(latest/'validity.nii.gz').dataobj).all()
        assert not np.asarray(nib.load(latest/'research_eligibility.nii.gz').dataobj).any()
    with store.open_case(case) as restored:
        assert not restored.review_journal_pending
        assert restored.state['status'] == 'practice_approved'


def test_export_aborts_if_review_changes_during_zip_write(setup, tmp_path, monkeypatch):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session: approve(session, *arrays(session))
    real_write = zipfile.ZipFile.write
    changed = []
    def write_and_change(archive, filename, *args, **kwargs):
        result = real_write(archive, filename, *args, **kwargs)
        if not changed:
            changed.append(True)
            with store.open_case(case) as session:
                lab, unc, _ = session.load()
                session.state['notes'] = 'Concurrent later review metadata'
                session.save_review_journal(lab, unc)
        return result
    monkeypatch.setattr(zipfile.ZipFile, 'write', write_and_change)
    destination = tmp_path/'Race results'
    with pytest.raises(ValidationError, match='changed while the ZIP'):
        export_approved(store, destination, include_practice=True)
    assert not list(destination.glob('*.zip'))


def test_ready_status_respects_uncertainty_and_summary_matches(setup):
    ds, store = setup
    case = ds.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty = arrays(session)
        for row in session.state['review']: row['reviewed'] = True
        session.state['compartments'] = {'medial': True, 'lateral': True}
        uncertainty[2, 4, 6] = 1
        assert core.status_label(session.state, uncertainty) != 'Ready for approval'
        session.save(labels, uncertainty, writer)
    summary = store.summary(case)
    assert summary['uncertainty_voxels'] == 1 and summary['display_status'] != 'Ready for approval'
