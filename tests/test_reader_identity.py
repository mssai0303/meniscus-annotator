"""Synthetic attribution and saved-work status checks; no human/MRI acceptance."""
import copy
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import core
from tools.make_synthetic import make_synthetic


@pytest.fixture
def data(tmp_path):
    return core.Dataset(make_synthetic(tmp_path / 'Synthetic reader sources', layout='flat'))


def job_for(data, annotator='Synthetic Reader A'):
    return {'schema_version': 'meniscus_job/1', 'dataset_identity': data.identity,
            'annotator': annotator,
            'protocol': {'version': 'synthetic-reader-pilot-1', 'status': 'draft'},
            'cases': {case.key: {'annotation_mode': 'blank'} for case in data.cases}}


def writer(path):
    path.write_bytes(b'SYNTHETIC CHECKPOINT TEST; NOT A REAL SEGMENTATION')


def save_practice(store, case):
    with store.open_case(case) as session:
        labels, uncertain, _ = session.load()
        labels[3, 10, 20] = 1
        labels[5, 20, 30] = 2
        session.state['last_slice'] = 5
        for row in session.state['review']:
            row['reviewed'] = True
        session.state['compartments'] = {'medial': True, 'lateral': True}
        return session.save(labels, uncertain, writer, approve=True, practice=True)


def file_hashes(root):
    return {str(path.relative_to(root)): core.sha256(path)
            for path in root.rglob('*') if path.is_file()}


def test_named_reader_save_resume_and_export_keep_explicit_attribution(data, tmp_path):
    job = job_for(data)
    job_before = copy.deepcopy(job)
    source_before = file_hashes(data.root)
    store = core.WorkStore(tmp_path / 'Named work', data, job)
    case = data.cases[1]
    checkpoint = save_practice(store, case)
    state = core.read_json(checkpoint / 'annotation.json')
    assert state['annotator'] == state['approver'] == job['annotator']
    assert state['job_identity'] == core.canonical(job)
    assert state['status'] == 'practice_approved'
    assert store.summary(case)['status'] == 'practice_approved'
    before = file_hashes(store.root)
    with core.WorkStore(store.root, data, job).open_case(case) as restored:
        assert restored.state['annotator'] == job['annotator']
        assert restored.state['approver'] == job['annotator']
        assert restored.state['last_slice'] == 5
        assert restored.load()[0][3, 10, 20] == 1
    assert file_hashes(store.root) == before
    output = core.export_approved(store, tmp_path / 'Reader results', include_practice=True)
    with zipfile.ZipFile(output) as archive:
        states = [json.loads(archive.read(name)) for name in archive.namelist()
                  if name.endswith('/annotation.json')]
        assert len(states) == 1
        assert states[0]['annotator'] == states[0]['approver'] == job['annotator']
    assert job == job_before and file_hashes(data.root) == source_before


@pytest.mark.parametrize('bad', [None, '', '   ', 7, False, ['Reader']])
def test_present_invalid_reader_is_rejected_before_case_work(data, tmp_path, bad):
    job = job_for(data, bad)
    with pytest.raises(core.ValidationError, match='annotator.*nonempty'):
        core.validate_job(data, job)
    with pytest.raises(core.ValidationError, match='annotator.*nonempty'):
        core.WorkStore(tmp_path / 'Rejected work', data, job)
    assert not (tmp_path / 'Rejected work' / 'cases').exists()


def test_software_practice_actor_wins_without_rewriting_job(data, tmp_path):
    job = job_for(data, 'Synthetic Named Reader')
    job['practice_context'] = {'purpose': 'software_practice', 'actor_type': 'automated',
                               'actor': 'Software QA (automated)'}
    before = copy.deepcopy(job)
    assert core.assigned_annotator(job) == 'Software QA (automated)'
    store = core.WorkStore(tmp_path / 'Software work', data, job)
    checkpoint = save_practice(store, data.cases[0])
    state = core.read_json(checkpoint / 'annotation.json')
    assert state['annotator'] == state['approver'] == 'Software QA (automated)'
    assert state['approval']['accepted_research_annotation'] is False
    assert job == before


def test_legacy_job_reader_is_preserved_without_rewriting_checkpoint(data, tmp_path):
    job = job_for(data)
    job.pop('annotator')
    assert core.assigned_annotator(job) is None and core.assigned_annotator(None) is None
    store = core.WorkStore(tmp_path / 'Legacy work', data, job, reader='Historical Reader')
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    annotation = checkpoint / 'annotation.json'
    state = core.read_json(annotation)
    state.pop('reader_assignment')
    annotation.write_text(json.dumps(state))
    manifest_path = checkpoint / 'manifest.json'
    manifest = core.read_json(manifest_path)
    manifest['files_sha256']['annotation.json'] = core.sha256(annotation)
    manifest_path.write_text(json.dumps(manifest))
    store.reader_assignment_path.unlink()
    before = file_hashes(store.root)
    with pytest.raises(core.ValidationError, match='different reader'):
        core.WorkStore(store.root, data, job, reader='Different Reader')
    assert file_hashes(store.root) == before
    verified = core.WorkStore(store.root, data, job, reader='Historical Reader', read_only=True)
    verified._validate_checkpoint(checkpoint, case)
    assert file_hashes(store.root) == before
    with core.WorkStore(store.root, data, copy.deepcopy(job), reader='Historical Reader').open_case(case) as restored:
        assert restored.state['annotator'] == restored.state['approver'] == 'Historical Reader'
        assert restored.current_checkpoint == checkpoint
        assert 'reader_assignment' not in restored.state
    after = file_hashes(store.root)
    after.pop('reader_assignment.json')
    assert after == before


def test_changed_reader_does_not_relabel_or_overwrite_saved_work(data, tmp_path):
    job = job_for(data)
    store = core.WorkStore(tmp_path / 'Bound work', data, job)
    case = data.cases[0]
    save_practice(store, case)
    before = file_hashes(store.root)
    changed = copy.deepcopy(job)
    changed['annotator'] = 'Synthetic Reader B'
    other = core.WorkStore(store.root, data, changed)
    assert other.summary(case)['status'] == 'saved_unavailable'
    with pytest.raises(core.ValidationError, match='No intact saved version'):
        other.open_case(case)
    assert file_hashes(store.root) == before
    with core.WorkStore(store.root, data, job).open_case(case) as restored:
        assert restored.state['annotator'] == 'Synthetic Reader A'


def test_summary_reports_changed_job_instead_of_approved_or_not_started(data, tmp_path):
    job = job_for(data)
    store = core.WorkStore(tmp_path / 'Protocol-bound work', data, job)
    case = data.cases[0]
    save_practice(store, case)
    before = file_hashes(store.root)
    changed = copy.deepcopy(job)
    changed['protocol']['version'] = 'synthetic-reader-pilot-2'
    other = core.WorkStore(store.root, data, changed)
    summary = other.summary(case)
    assert summary['status'] == 'configuration_mismatch'
    assert summary['previous_status'] == 'practice_approved'
    assert summary['reviewed'] == case.n_slices and summary['last_slice'] == 5
    with pytest.raises(core.ValidationError, match='Saved initialization permissions differ'):
        other.open_case(case)
    assert file_hashes(store.root) == before


def test_summary_preserves_saved_work_warning_for_corruption(data, tmp_path):
    store = core.WorkStore(tmp_path / 'Damaged work', data, job_for(data))
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    (checkpoint / 'labels.nii.gz').write_bytes(b'SYNTHETIC CORRUPTION')
    before = file_hashes(store.root)
    summary = store.summary(case)
    assert summary['status'] == 'saved_unavailable'
    assert summary['checkpoint'] is None
    assert 'Saved work exists' in summary['reason']
    assert file_hashes(store.root) == before
    assert store.summary(data.cases[1])['status'] == 'not_started'


def test_summary_recovers_older_intact_checkpoint_without_changing_files(data, tmp_path):
    store = core.WorkStore(tmp_path / 'Recoverable work', data, job_for(data))
    case = data.cases[0]
    first = save_practice(store, case)
    second = save_practice(store, case)
    assert second != first
    (second / 'annotation.json').write_text('SYNTHETIC CORRUPTION')
    before = file_hashes(store.root)
    summary = store.summary(case)
    assert summary['status'] == 'practice_approved' and summary['checkpoint'] == first.name
    assert file_hashes(store.root) == before


def test_version_incompatible_saved_work_is_not_presented_as_new(data, tmp_path):
    store = core.WorkStore(tmp_path / 'Older version work', data, job_for(data))
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    annotation = checkpoint / 'annotation.json'
    state = core.read_json(annotation)
    state['app_version'] = 'SYNTHETIC-INCOMPATIBLE-VERSION'
    annotation.write_text(json.dumps(state))
    manifest_file = checkpoint / 'manifest.json'
    manifest = core.read_json(manifest_file)
    manifest['files_sha256']['annotation.json'] = core.sha256(annotation)
    manifest_file.write_text(json.dumps(manifest))
    before = file_hashes(store.root)
    assert store.summary(case)['status'] == 'saved_unavailable'
    with pytest.raises(core.ValidationError, match='No intact saved version'):
        store.open_case(case)
    assert file_hashes(store.root) == before


def test_reader_tampering_is_rejected_in_existing_checkpoint_validation(data, tmp_path):
    store = core.WorkStore(tmp_path / 'Attribution checks', data, job_for(data))
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    state = core.read_json(checkpoint / 'annotation.json')
    state['annotator'] = 'Different Reader'
    with pytest.raises(core.ValidationError, match='actor differs'):
        store._validate_state(state, case)


@pytest.mark.parametrize('reader', [None, '', '  ', 12, False])
def test_unassigned_job_never_invents_a_reader(data, tmp_path, reader):
    job = job_for(data)
    job.pop('annotator')
    work = tmp_path / 'Not created'
    with pytest.raises(core.ValidationError, match='reader name or study ID'):
        core.WorkStore(work, data, job, reader=reader)
    assert not work.exists()


def test_local_readers_save_resume_export_without_changing_source_job(data, tmp_path):
    from MeniscusAnnotatorLib.reader_workspace import reader_workspace
    job = job_for(data)
    job.pop('annotator')
    original = copy.deepcopy(job)
    before = file_hashes(data.root)
    stores = []
    for reader in ('Synthetic Reader A', 'Synthetic Reader B'):
        plan = reader_workspace(data.version, job, reader=reader)
        store = core.WorkStore(tmp_path / 'Work' / plan['relative_folder'], data, job, reader=reader)
        checkpoint = save_practice(store, data.cases[0])
        state = core.read_json(checkpoint / 'annotation.json')
        assert state['annotator'] == state['approver'] == reader
        assert state['job_identity'] == core.canonical(job)
        assert state['reader_assignment'] == store.reader_assignment == core.read_json(store.reader_assignment_path)
        stores.append(store)
    assert stores[0].root != stores[1].root
    first_bytes = file_hashes(stores[0].root)
    with pytest.raises(core.ValidationError, match='different reader'):
        core.WorkStore(stores[0].root, data, job, reader='Synthetic Reader B')
    assert first_bytes == file_hashes(stores[0].root)
    with core.WorkStore(stores[0].root, data, job, reader=' Synthetic Reader A ').open_case(data.cases[0]) as restored:
        assert restored.state['annotator'] == 'Synthetic Reader A'
        assert restored.state['last_slice'] == 5
    archive = core.export_approved(stores[0], tmp_path / 'Results', include_practice=True)
    with zipfile.ZipFile(archive) as bundle:
        annotations = [json.loads(bundle.read(name)) for name in bundle.namelist() if name.endswith('/annotation.json')]
        assert len(annotations) == 1
        assert annotations[0]['annotator'] == annotations[0]['approver'] == 'Synthetic Reader A'
        assert annotations[0]['reader_assignment'] == stores[0].reader_assignment
    assert job == original and file_hashes(data.root) == before


def test_changed_local_binding_blocks_active_save_reopen_and_export(data, tmp_path):
    job = job_for(data)
    job.pop('annotator')
    store = core.WorkStore(tmp_path / 'Bound local work', data, job, reader='Synthetic Reader A')
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        original = store.reader_assignment_path.read_bytes()
        changed = copy.deepcopy(store.reader_assignment)
        changed['reader'] = 'Synthetic Reader B'
        store.reader_assignment_path.write_text(json.dumps(changed))
        with pytest.raises(core.ValidationError, match='local reader assignment changed'):
            session.save(labels, uncertainty, writer)
        with pytest.raises(core.ValidationError, match='local reader assignment changed'):
            session.load()
    with pytest.raises(core.ValidationError, match='local reader assignment changed'):
        core.export_approved(store, tmp_path / 'No export', include_practice=True)
    store.reader_assignment_path.write_bytes(original)
    with core.WorkStore(store.root, data, job, reader='Synthetic Reader A').open_case(case) as restored:
        assert restored.current_checkpoint == checkpoint


def test_explicit_job_cannot_be_overridden_by_local_reader(data, tmp_path):
    work = tmp_path / 'Rejected override'
    with pytest.raises(core.ValidationError, match='differs from the explicit job'):
        core.WorkStore(work, data, job_for(data), reader='Different Reader')
    assert not work.exists()


def test_legacy_reader_reconnection_recovers_older_intact_checkpoint(data, tmp_path):
    job = job_for(data)
    job.pop('annotator')
    store = core.WorkStore(tmp_path / 'Legacy recovery', data, job, reader='Historical Reader')
    case = data.cases[0]
    first = save_practice(store, case)
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        session.state['notes'] = 'Synthetic newer draft that will be damaged'
        latest = session.save(labels, uncertainty, writer)
    for checkpoint in (first, latest):
        annotation = checkpoint / 'annotation.json'
        state = core.read_json(annotation)
        state.pop('reader_assignment')
        annotation.write_text(json.dumps(state), encoding='utf-8')
        manifest_path = checkpoint / 'manifest.json'
        manifest = core.read_json(manifest_path)
        manifest['files_sha256']['annotation.json'] = core.sha256(annotation)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    store.reader_assignment_path.unlink()
    (latest / 'annotation.json').write_text('damaged synthetic checkpoint', encoding='utf-8')
    before = file_hashes(store.root)
    checker = core.WorkStore(store.root, data, job, reader='Historical Reader', read_only=True)
    checker._validate_checkpoint(first, case)
    assert file_hashes(store.root) == before
    with core.WorkStore(store.root, data, job, reader='Historical Reader').open_case(case) as restored:
        assert restored.recovered
        assert restored.current_checkpoint == first
        assert restored.state['annotator'] == restored.state['approver'] == 'Historical Reader'
        assert 'reader_assignment' not in restored.state
    after = file_hashes(store.root)
    after.pop('reader_assignment.json')
    assert after == before


@pytest.mark.parametrize('competing_reader', ['Synthetic Reader A', 'Synthetic Reader B'])
def test_reader_binding_created_during_open_is_revalidated(data, tmp_path, monkeypatch, competing_reader):
    work = (tmp_path / 'Concurrent local work').resolve()
    original_mkdir = Path.mkdir
    inserted = []
    competing_binding = {'schema_version': 'meniscus_reader_assignment/1',
                         'dataset_identity': data.identity,
                         'base_job_identity': None, 'reader': competing_reader}

    def concurrent_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path == work and not inserted:
            inserted.append(True)
            core.write_json(work / 'reader_assignment.json', competing_binding)
        return result

    monkeypatch.setattr(Path, 'mkdir', concurrent_mkdir)
    if competing_reader != 'Synthetic Reader A':
        with pytest.raises(core.ValidationError, match='claimed by a different reader'):
            core.WorkStore(work, data, reader='Synthetic Reader A')
        assert not (work / 'cases').exists()
    else:
        store = core.WorkStore(work, data, reader='Synthetic Reader A')
        assert store._reader_assignment_persisted
        assert store.reader_assignment == competing_binding
        store.case_resolution(data.cases[0])
    assert inserted and core.read_json(work / 'reader_assignment.json') == competing_binding


def test_read_only_store_cannot_be_used_via_public_case_session_constructor(data, tmp_path):
    work = tmp_path / 'Read-only verification'
    core.WorkStore(work, data, reader='Synthetic Reader')
    store = core.WorkStore(work, data, reader='Synthetic Reader', read_only=True)
    before = file_hashes(work)
    case = data.cases[0]
    with pytest.raises(core.ValidationError, match='Read-only verification'):
        store.open_case(case)
    with pytest.raises(core.ValidationError, match='Read-only verification'):
        core.CaseSession(store, case)
    assert not store.case_folder(case).exists()
    assert file_hashes(work) == before
