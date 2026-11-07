"""Synthetic folder-layout compatibility and saved-work reconnection tests."""
import csv
import json
from pathlib import Path
import shutil
import sys
import zipfile

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib.core import Dataset, WorkStore, ValidationError, case_folder_options, export_approved, sha256
from tools.make_synthetic import make_synthetic


def rows(source):
    with (source / 'case_index.csv').open(newline='') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def index_write(source, fields, values):
    with (source / 'case_index.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def seg_writer(path):
    path.write_bytes(b'SYNTHETIC marker, real Slicer writer tested separately')
    return True


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
def test_both_layouts_keep_original_input_checks_and_workflow(tmp_path, layout):
    source = make_synthetic(tmp_path / 'Source with spaces', layout=layout)
    before = {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()}
    dataset = Dataset(source)
    assert len(dataset.cases) == 2
    assert all(c.folder.relative_to(source).as_posix() == case_folder_options(c.metadata)[0 if layout == 'flat' else 1] for c in dataset.cases)
    if layout == 'flat':
        assert all({p.name for p in c.folder.iterdir()} == {'image.nii.gz', 'case.json', 'slice_review.csv'} for c in dataset.cases)
    store = WorkStore(tmp_path / 'Local work', dataset, reader='Synthetic Reader')
    case = dataset.cases[1]
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        labels[5, 13, 17] = 1
        labels[5, 15, 22] = 2
        for review in session.state['review']:
            review['reviewed'] = True
        session.state['compartments'] = {'medial': True, 'lateral': True}
        session.state['last_slice'] = 5
        session.save(labels, uncertainty, seg_writer, approve=True, practice=True)
    with store.open_case(case) as reopened:
        actual, uncertain, _ = reopened.load()
        assert np.array_equal(actual, labels)
        assert np.array_equal(uncertain, uncertainty)
        assert reopened.state['last_slice'] == 5
    output = export_approved(store, tmp_path / 'Results', [case.key], include_practice=True)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read('results.json'))['practice_only']
    assert before == {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()}


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
@pytest.mark.parametrize('field,value', [('participant_id', 'WRONG_SYNTHETIC'), ('visit_month', 72), ('knee_side', 'R')])
def test_wrong_folder_identity_rejected(tmp_path, layout, field, value):
    source = make_synthetic(tmp_path / 'Source', layout=layout)
    dataset = Dataset(source)
    case = dataset.cases[0]
    fake = dict(case.metadata, **{field: value})
    target_relative = case_folder_options(fake)[0 if layout == 'flat' else 1]
    target = source / target_relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(case.folder), target)
    fields, values = rows(source)
    values[0]['relative_folder'] = target_relative
    index_write(source, fields, values)
    with pytest.raises(ValidationError, match='folder does not match'):
        Dataset(source)


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
@pytest.mark.parametrize('relative', ['../elsewhere', '/absolute/elsewhere', 'Cases\\escape', 'Cases/../escape', 'Cases//alias', './Cases/alias'])
def test_invalid_source_paths_rejected(tmp_path, layout, relative):
    source = make_synthetic(tmp_path / 'Source', layout=layout)
    fields, values = rows(source)
    values[0]['relative_folder'] = relative
    index_write(source, fields, values)
    with pytest.raises(ValidationError):
        Dataset(source)


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
def test_duplicate_cases_rejected(tmp_path, layout):
    source = make_synthetic(tmp_path / 'Source', layout=layout)
    fields, values = rows(source)
    values.append(dict(values[0]))
    index_write(source, fields, values)
    with pytest.raises(ValidationError, match='duplicate case'):
        Dataset(source)


def test_source_key_reuse_rejected_even_in_flat_names(tmp_path):
    source = make_synthetic(tmp_path / 'Source', layout='flat')
    dataset = Dataset(source)
    second = dataset.cases[1]
    metadata = dict(second.metadata, source_series_key=dataset.cases[0].metadata['source_series_key'])
    (second.folder / 'case.json').write_text(json.dumps(metadata))
    with pytest.raises(ValidationError, match='source-series key'):
        Dataset(source)


def test_old_saved_work_reconnects_after_folder_only_migration(tmp_path):
    source = make_synthetic(tmp_path / 'Old source')
    dataset = Dataset(source)
    case = dataset.cases[1]
    location = tmp_path / 'Local work preserved'
    store = WorkStore(location, dataset, reader='Synthetic Reader')
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        labels[5, 13, 17] = 1
        session.state['notes'] = 'Synthetic saved notes before folder relocation'
        session.state['last_slice'] = 5
        session.save(labels, uncertainty, seg_writer)
    work_before = {p.relative_to(location).as_posix(): sha256(p) for p in location.rglob('*') if p.is_file()}
    new_source = tmp_path / 'Flat source relocated'
    new_source.mkdir()
    shutil.copyfile(source / 'README.txt', new_source / 'README.txt')
    fields, values = rows(source)
    for old_case, row in zip(dataset.cases, values):
        new_relative = case_folder_options(old_case.metadata)[0]
        new_folder = new_source / new_relative
        new_folder.mkdir(parents=True)
        for name in ['image.nii.gz', 'case.json', 'slice_review.csv']:
            shutil.copyfile(old_case.folder / name, new_folder / name)
        row['relative_folder'] = new_relative
    index_write(new_source, fields, values)
    migrated = Dataset(new_source)
    assert migrated.identity == dataset.identity
    assert [(c.key, c.identity) for c in migrated.cases] == [(c.key, c.identity) for c in dataset.cases]
    with WorkStore(location, migrated, reader='Synthetic Reader').open_case(migrated.by_key[case.key]) as resumed:
        assert resumed.state['notes'] == 'Synthetic saved notes before folder relocation'
        assert resumed.state['last_slice'] == 5
        assert np.array_equal(resumed.load()[0], labels)
    assert work_before == {p.relative_to(location).as_posix(): sha256(p) for p in location.rglob('*') if p.is_file()}


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
def test_case_folder_symlink_rejected_in_both_layouts(tmp_path, layout):
    source = make_synthetic(tmp_path / 'Source', layout=layout)
    case = Dataset(source).cases[0]
    external = tmp_path / 'External source'
    shutil.move(str(case.folder), external)
    case.folder.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValidationError):
        Dataset(source)


def test_flat_image_checksum_guard_unchanged(tmp_path):
    source = make_synthetic(tmp_path / 'Source', layout='flat')
    image = Dataset(source).cases[0].image_path
    data = bytearray(image.read_bytes())
    data[-1] ^= 1
    image.write_bytes(data)
    with pytest.raises(ValidationError, match='checksum changed'):
        Dataset(source)


@pytest.mark.parametrize('layout', ['legacy', 'flat'])
@pytest.mark.parametrize('month,side', [(0, 'L'), (0, 'R'), (72, 'L'), (72, 'R'), (96, 'L'), (96, 'R')])
def test_selected_visit_and_side_names_are_supported(tmp_path, layout, month, side):
    source = make_synthetic(tmp_path / 'Source', layout=layout)
    original = Dataset(source).cases[0]
    # Configure a new synthetic fixture identity, never alter a real source case.
    metadata = dict(original.metadata, visit_month=month, knee_side=side)
    new_relative = case_folder_options(metadata)[0 if layout == 'flat' else 1]
    new_folder = source / new_relative
    if new_folder != original.folder:
        new_folder.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(original.folder), new_folder)
    (new_folder / 'case.json').write_text(json.dumps(metadata))
    fields, values = rows(source)
    values[0].update(visit_month=str(month), knee_side=side, relative_folder=new_relative)
    index_write(source, fields, values)
    actual = Dataset(source).by_key[metadata['case_key']]
    assert actual.metadata['visit_month'] == month
    assert actual.metadata['knee_side'] == side
