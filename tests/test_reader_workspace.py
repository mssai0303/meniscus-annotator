"""Pure assignment-location tests; no MRI access, folders or settings written."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'MeniscusAnnotatorLib' / 'reader_workspace.py'
SPEC = importlib.util.spec_from_file_location('reader_workspace_under_test', MODULE)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
reader_workspace = HELPER.reader_workspace


def job_for(reader='Synthetic Doctor A'):
    return {'schema_version': 'meniscus_job/1', 'dataset_identity': 'SYNTHETIC-DATASET',
            'annotator': reader, 'protocol': {'version': 'pilot-1', 'status': 'draft'},
            'cases': {'SYNTHETIC_A': {'annotation_mode': 'correction', 'availability': 'unresolved',
                                      'reason': 'Synthetic unresolved fixture', 'starting_mask': None}}}


class BoundJob(dict):
    """Small stand-in for the source_job property of BoundCorrectionJob."""
    def __init__(self, effective, original):
        super().__init__(copy.deepcopy(effective))
        self.source_job = copy.deepcopy(original)


def test_two_assigned_readers_get_different_work_and_settings():
    first = reader_workspace('SYNTHETIC_V1', job_for('Synthetic Doctor A'))
    second = reader_workspace('SYNTHETIC_V1', job_for('Synthetic Doctor B'))
    assert first['uses_named_assignment'] and second['uses_named_assignment']
    assert first['relative_folder'] != second['relative_folder']
    assert first['settings_key'] != second['settings_key']
    assert first['legacy_settings_key'] == second['legacy_settings_key'] == 'Meniscus/work/SYNTHETIC_V1'
    assert first['settings_key'] != first['legacy_settings_key']


@pytest.mark.parametrize('change', ['protocol', 'status', 'dataset_binding', 'case_rule'])
def test_immutable_job_changes_get_a_separate_assignment(change):
    first = job_for()
    second = copy.deepcopy(first)
    if change == 'protocol': second['protocol']['version'] = 'pilot-2'
    if change == 'status': second['protocol']['status'] = 'released'
    if change == 'dataset_binding': second['dataset_identity'] = 'SYNTHETIC-OTHER-DATASET'
    if change == 'case_rule': second['cases']['SYNTHETIC_A']['reason'] = 'Different original permission'
    assert reader_workspace('SYNTHETIC_V1', first)['relative_folder'] != reader_workspace('SYNTHETIC_V1', second)['relative_folder']


def test_additive_resolution_keeps_original_assignment_path_and_key():
    original = job_for()
    effective = copy.deepcopy(original)
    effective['cases']['SYNTHETIC_A'] = {'annotation_mode': 'correction', 'availability': 'ready',
                                       'starting_mask': {'path': 'Cases/SYNTHETIC_A/starting_mask.nii.gz',
                                                         'sha256': '0' * 64, 'source': 'SYNTHETIC', 'version': '1'}}
    before_original, before_effective = copy.deepcopy(original), copy.deepcopy(effective)
    bound = BoundJob(effective, original)
    expected = reader_workspace('SYNTHETIC_V1', original)
    assert reader_workspace('SYNTHETIC_V1', bound) == expected
    assert reader_workspace('SYNTHETIC_V1', effective) != expected
    # An unrelated additive permission also leaves the base assignment fixed.
    bound['cases']['SYNTHETIC_B'] = {'annotation_mode': 'blank'}
    assert reader_workspace('SYNTHETIC_V1', bound) == expected
    assert original == before_original and effective == before_effective


def test_hash_is_the_canonical_base_job_not_dict_insertion_order():
    job = job_for()
    expected = hashlib.sha256(json.dumps(job, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()
    plan = reader_workspace('SYNTHETIC_V1', job)
    assert plan['base_job_identity'] == expected
    assert plan['settings_key'].endswith(expected)
    assert plan['relative_folder'].name == 'assignment-' + expected[:24]
    assert reader_workspace('SYNTHETIC_V1', dict(reversed(list(job.items())))) == plan


@pytest.mark.parametrize('job', [None, {}, {'protocol': {'version': 'legacy', 'status': 'draft'}}])
def test_legacy_version_only_path_and_settings_are_unchanged(job):
    plan = reader_workspace('SYNTHETIC_V1', job)
    assert not plan['uses_named_assignment']
    assert plan['relative_folder'] == Path('SYNTHETIC_V1')
    assert plan['settings_key'] == plan['legacy_settings_key'] == 'Meniscus/work/SYNTHETIC_V1'


@pytest.mark.parametrize('actor_type,actor', [
    ('automated', 'Software QA (automated)'),
    ('human_unverified', 'Preview user (identity unverified)'),
])
def test_software_practice_keeps_legacy_location_even_with_named_job(actor_type, actor):
    job = job_for()
    job['practice_context'] = {'purpose': 'software_practice', 'actor_type': actor_type, 'actor': actor}
    plan = reader_workspace('SYNTHETIC_V1', job)
    assert not plan['uses_named_assignment']
    assert plan['relative_folder'] == Path('SYNTHETIC_V1')
    assert plan['settings_key'] == 'Meniscus/work/SYNTHETIC_V1'


@pytest.mark.parametrize('name', ['Dr Élodie 陈', 'Dr A/B:CON', '../Synthetic/Reader', 'NUL', 'Synthetic Doctor 👩‍⚕️'])
def test_reader_name_never_becomes_a_filesystem_component(name):
    plan = reader_workspace('SYNTHETIC_V1', job_for(name))
    assert plan['relative_folder'].parts[0] == 'SYNTHETIC_V1'
    assert len(plan['relative_folder'].parts) == 2
    assert re.fullmatch(r'assignment-[0-9a-f]{24}', plan['relative_folder'].name)
    assert str(plan['relative_folder']).isascii() and plan['settings_key'].isascii()


@pytest.mark.parametrize('version', ['../escape', 'bad/path', 'bad\\path', 'CON', 'NUL.txt', 'COM1', 'version.', '', 'x' * 101])
def test_invalid_dataset_version_is_rejected(version):
    with pytest.raises(ValueError, match='portable folder identifier'):
        reader_workspace(version, job_for())


@pytest.mark.parametrize('name', [None, '', '   ', 123])
def test_invalid_explicit_reader_does_not_fall_back_to_legacy(name):
    with pytest.raises(ValueError, match='nonempty name'):
        reader_workspace('SYNTHETIC_V1', job_for(name))


def test_planning_does_not_create_folder_or_mutate_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = job_for()
    before = copy.deepcopy(job)
    plan = reader_workspace('SYNTHETIC_V1', job)
    destination = tmp_path / 'Meniscus_annotation_work' / plan['relative_folder']
    assert not destination.exists() and list(tmp_path.iterdir()) == []
    assert job == before
