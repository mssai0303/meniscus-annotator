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
    assert core.assigned_annotator(job) == core.assigned_annotator(None) == 'Jeff'
    store = core.WorkStore(tmp_path / 'Legacy work', data, job)
    case = data.cases[0]
    checkpoint = save_practice(store, case)
    before = file_hashes(store.root)
    with core.WorkStore(store.root, data, copy.deepcopy(job)).open_case(case) as restored:
        assert restored.state['annotator'] == restored.state['approver'] == 'Jeff'
        assert restored.current_checkpoint == checkpoint
    assert file_hashes(store.root) == before


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
    state['annotator'] = 'Jeff'
    with pytest.raises(core.ValidationError, match='actor differs'):
        store._validate_state(state, case)
