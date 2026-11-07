"""Synthetic-only checks of software-practice separation and honest attribution."""
import copy
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import nibabel as nib
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import Dataset, WorkStore, ValidationError, export_approved, sha256
from tools.make_synthetic import make_synthetic

ACTORS = {'automated': 'Software QA (automated)',
          'human_unverified': 'Preview user (identity unverified)'}


@pytest.fixture
def data(tmp_path):
    return Dataset(make_synthetic(tmp_path / 'Synthetic sources', layout='flat'))


def job_for(data, actor_type='automated'):
    return {'schema_version': 'meniscus_job/1', 'dataset_identity': data.identity,
            'protocol': {'version': 'software-practice-test-1', 'status': 'draft'},
            'practice_context': {'purpose': 'software_practice',
                                 'actor': ACTORS[actor_type], 'actor_type': actor_type},
            'cases': {case.key: {'annotation_mode': 'blank'} for case in data.cases}}


def writer(path):
    # Native storage is exercised separately in Slicer; this is a persistence marker.
    path.write_bytes(b'SYNTHETIC PERSISTENCE TEST ONLY')


def reviewed(session):
    for row in session.state['review']:
        row['reviewed'] = True
    session.state['compartments'] = {'medial': True, 'lateral': True}


@pytest.mark.parametrize('actor_type', list(ACTORS))
def test_software_practice_save_reopen_export_is_honestly_attributed(data, tmp_path, actor_type):
    job = job_for(data, actor_type)
    store = WorkStore(tmp_path / 'Isolated software practice', data, job)
    before = {str(p): sha256(p) for p in data.root.rglob('*') if p.is_file()}
    case = data.cases[1]
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        labels[3, 10, 20] = 1
        labels[3, 20, 30] = 2
        reviewed(session)
        with pytest.raises(ValidationError, match='SOFTWARE PRACTICE'):
            session.save(labels, uncertainty, writer, approve=True, practice=False)
        checkpoint = session.save(labels, uncertainty, writer, approve=True, practice=True)
        metadata = json.loads((checkpoint / 'annotation.json').read_text(encoding='utf-8'))
        assert metadata['annotator'] == metadata['approver'] == ACTORS[actor_type]
        assert metadata['practice_context'] == job['practice_context']
        assert metadata['annotation_purpose'] == 'software_practice'
        assert metadata['status'] == 'practice_approved'
        approval = metadata['approval']
        assert approval['practice_only'] is True
        assert approval['accepted_research_annotation'] is False
        assert approval['human_anatomical_approval'] is False
        assert approval['deliberate_approval_required_by_ui'] is (actor_type != 'automated')
        assert approval['approval_type'] == ('automated_software_check' if actor_type == 'automated' else 'manual_software_practice')
        assert 'Synthetic Reader' not in json.dumps(metadata)
        assert not np.asarray(nib.load(checkpoint / 'validity.nii.gz').dataobj).any()
    with store.open_case(case) as reopened:
        actual, uncertain, _ = reopened.load()
        assert np.array_equal(actual, labels) and np.array_equal(uncertain, uncertainty)
        assert reopened.state['approver'] == ACTORS[actor_type]
    with pytest.raises(ValidationError, match='No eligible'):
        export_approved(store, tmp_path / 'Research output')
    archive_path = export_approved(store, tmp_path / 'Separate practice results', include_practice=True)
    assert archive_path.name.startswith('SOFTWARE_PRACTICE_ONLY-')
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('results.json'))
        text = archive.read('README.txt').decode()
        assert manifest['practice_only'] is True and manifest['software_practice'] is True
        assert manifest['accepted_research_annotation'] is False
        assert manifest['human_anatomical_approval'] is False
        assert manifest['practice_context'] == job['practice_context']
        assert 'SOFTWARE PRACTICE' in text and 'NOT ACCEPTED RESEARCH' in text
        assert 'Synthetic Reader' not in text + json.dumps(manifest)
        exported_validity = tmp_path / 'exported-validity.nii.gz'
        exported_validity.write_bytes(archive.read(manifest['cases'][0]['folder'] + '/validity.nii.gz'))
        assert not np.asarray(nib.load(exported_validity).dataobj).any()
        assert 'Every validity voxel is zero' in text
        assert not any(name.endswith('/image.nii.gz') for name in archive.namelist())
    assert before == {str(p): sha256(p) for p in data.root.rglob('*') if p.is_file()}


def test_software_practice_binding_cannot_be_opened_as_production_or_other_actor(data, tmp_path):
    location = tmp_path / 'Automation-only work'
    WorkStore(location, data, job_for(data))
    with pytest.raises(ValidationError, match='practice scope'):
        WorkStore(location, data, reader='Synthetic Reader')
    with pytest.raises(ValidationError, match='practice scope'):
        WorkStore(location, data, job_for(data, 'human_unverified'))
    assert json.loads((location / 'dataset.json').read_text(encoding='utf-8'))['practice_context']['actor_type'] == 'automated'


def test_existing_production_work_cannot_receive_software_practice(data, tmp_path):
    location = tmp_path / 'Production-only work'
    WorkStore(location, data, reader='Synthetic Reader')
    with pytest.raises(ValidationError, match='practice scope'):
        WorkStore(location, data, job_for(data))


@pytest.mark.parametrize('change', ['released', 'purpose', 'actor', 'type', 'extra', 'missing', 'empty'])
def test_invalid_or_misleading_practice_context_rejected(data, tmp_path, change):
    job = job_for(data)
    if change == 'released': job['protocol']['status'] = 'released'
    if change == 'purpose': job['practice_context']['purpose'] = 'research'
    if change == 'actor': job['practice_context']['actor'] = 'Synthetic Reader'
    if change == 'type': job['practice_context']['actor_type'] = 'independent_reader'
    if change == 'extra': job['practice_context']['research_approved'] = True
    if change == 'missing': del job['practice_context']['actor_type']
    if change == 'empty': job['practice_context'] = {}
    with pytest.raises(ValidationError):
        WorkStore(tmp_path / 'Invalid practice', data, job)


@pytest.mark.parametrize('change', ['actor', 'context', 'purpose', 'released', 'protocol_version', 'research_status', 'approval_actor', 'approval_type', 'human_claim', 'deliberate_claim'])
def test_corrupt_or_promoted_practice_state_rejected(data, tmp_path, change):
    store = WorkStore(tmp_path / 'Software QA', data, job_for(data))
    case = data.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        reviewed(session)
        session.save(labels, uncertainty, writer, approve=True, practice=True)
        state = copy.deepcopy(session.state)
        if change == 'actor': state['annotator'] = 'Synthetic Reader'
        if change == 'context': state['practice_context'] = None
        if change == 'purpose': state['annotation_purpose'] = 'research_annotation'
        if change == 'released': state['protocol']['status'] = 'released'
        if change == 'protocol_version': state['protocol']['version'] = 'invented-unconfigured-version'
        if change == 'research_status': state['status'] = 'approved'
        if change == 'approval_actor': state['approver'] = 'Synthetic Reader'
        if change == 'approval_type': state['approval']['approval_type'] = 'manual_software_practice'
        if change == 'human_claim': state['approval']['human_anatomical_approval'] = True
        if change == 'deliberate_claim': state['approval']['deliberate_approval_required_by_ui'] = True
        with pytest.raises(ValidationError):
            store._validate_state(state, case)


@pytest.mark.parametrize('default_encoding', ['utf-8', 'cp1252'])
def test_explicit_reader_preserves_legacy_missing_context_and_assignment(data, tmp_path, monkeypatch, default_encoding):
    # Emulate a Windows locale even on the Mac/Linux test host. JSON fixtures
    # must use UTF-8 explicitly, as the actual checkpoint reader/writer does.
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
    location = tmp_path / 'Ordinary annotation'
    store = WorkStore(location, data, reader='Historical Reader')
    case = data.cases[0]
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        reviewed(session)
        checkpoint = session.save(labels, uncertainty, writer, approve=True, practice=True)
        assert session.state['annotator'] == session.state['approver'] == 'Historical Reader'
        assert session.state['approval']['deliberate_approval_required_by_ui'] is True
        assert 'approval_type' not in session.state['approval']
        assert np.asarray(nib.load(checkpoint / 'validity.nii.gz').dataobj).all()
    binding = json.loads((location / 'dataset.json').read_text(encoding='utf-8'))
    assert 'practice_context' not in binding
    state_path = checkpoint / 'annotation.json'
    legacy = json.loads(state_path.read_text(encoding='utf-8'))
    legacy.pop('practice_context')
    legacy.pop('annotation_purpose')
    legacy.pop('reader_assignment')
    state_path.write_text(json.dumps(legacy), encoding='utf-8')
    manifest_path = checkpoint / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['files_sha256']['annotation.json'] = sha256(state_path)
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    (location / 'reader_assignment.json').unlink()
    original_files = {p.relative_to(location).as_posix(): sha256(p) for p in location.rglob('*') if p.is_file()}
    store = WorkStore(location, data, reader='Historical Reader')
    with store.open_case(case) as reopened:
        assert reopened.state['annotator'] == reopened.state['approver'] == 'Historical Reader'
        assert 'reader_assignment' not in reopened.state
        assert reopened.load()[0].shape == labels.shape
    assert all(sha256(location / name) == digest for name, digest in original_files.items())
    assert json.loads((location / 'reader_assignment.json').read_text(encoding='utf-8'))['reader'] == 'Historical Reader'
    result = export_approved(store, tmp_path / 'Ordinary practice results', include_practice=True)
    assert result.name.startswith('PRACTICE_ONLY-')
    with zipfile.ZipFile(result) as archive:
        assert json.loads(archive.read('results.json'))['software_practice'] is False


def test_validity_remains_review_based_outside_software_practice():
    from MeniscusAnnotatorLib.core import validity_array
    uncertain = np.zeros((3, 4, 5), dtype=np.uint8)
    uncertain[1, 2, 3] = 1
    state = {'review': [{'reviewed': False, 'flag': False},
                        {'reviewed': True, 'flag': False},
                        {'reviewed': True, 'flag': True}]}
    actual = validity_array(state, uncertain)
    assert not actual[0].any() and not actual[2].any()
    assert actual[1].sum() == 19 and actual[1, 2, 3] == 0
    state['practice_context'] = {'purpose': 'software_practice', 'actor': ACTORS['automated'], 'actor_type': 'automated'}
    assert not validity_array(state, uncertain).any()
