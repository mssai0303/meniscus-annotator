"""Validate the shipped procedural correction fixture without Qt or MRI data."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from MeniscusAnnotatorLib import core

spec = importlib.util.spec_from_file_location('fixture_under_test', REPO / 'packaging/prebuilt/make_correction_synthetic.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize('automated', [False, True])
def test_installed_fixture_autoloads_exact_flat_correction_masks(tmp_path, automated):
    root = fixture.make_correction_synthetic(tmp_path / 'Synthetic correction sources', automated=automated)
    dataset = core.Dataset(root)
    before = {p.relative_to(root).as_posix(): core.sha256(p) for p in root.rglob('*') if p.is_file()}
    job, job_path = core.load_dataset_job_config(dataset)
    validation = core.validate_job(dataset, job, require_full_correction=True)
    assert validation['verified_masks'] == 2 and validation['unresolved_cases'] == 0
    assert Path(job_path) == root / 'correction_job.json'
    assert all(case.folder.parent.name == 'Cases' for case in dataset.cases)
    store = core.WorkStore(tmp_path / 'Separate work', dataset, job)
    for case in dataset.cases:
        with store.open_case(case) as session:
            values, uncertain, _ = session.load()
            assert session.state['initialization']['method'] == 'correction'
            assert set(np.unique(values)) == {0, 1, 2} and not uncertain.any()
            assert session.state['annotator'] == core.PRACTICE_ACTORS['automated' if automated else 'human_unverified']
            assert session.state['annotation_purpose'] == 'software_practice'
            assert session.state['approval'] is None
            assert session.approval_errors(values, uncertain, practice=False)
    assert before == {p.relative_to(root).as_posix(): core.sha256(p) for p in root.rglob('*') if p.is_file()}


def test_installed_fixture_refuses_existing_dataset(tmp_path):
    root = fixture.make_correction_synthetic(tmp_path / 'Existing', automated=True)
    before = core.sha256(root / 'correction_job.json')
    with pytest.raises(ValueError, match='already contains'):
        fixture.make_correction_synthetic(root)
    assert core.sha256(root / 'correction_job.json') == before
