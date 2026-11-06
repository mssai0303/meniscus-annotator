"""Byte-preserving migration mechanics; image validation is tested by the adapter."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('migrate_dataset_layout', TOOLS / 'migrate_dataset_layout.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def source_fixture(tmp_path):
    root = tmp_path / 'old'
    folder = root / 'Cases/OAI_SYNTHETIC_CASE/M072/RIGHT/series_SYNTHETIC_SERIES'
    folder.mkdir(parents=True)
    (folder / 'annotations').mkdir()
    image = b'SYNTHETIC BYTE-PRESERVATION FIXTURE; NOT A NIFTI IMAGE'
    (folder / 'image.nii.gz').write_bytes(image)
    metadata = {'participant_id': 'SYNTHETIC_CASE', 'visit_month': 72, 'knee_side': 'R', 'source_series_key': 'SYNTHETIC_SERIES', 'series_instance_uid': 'SYNTHETIC_UID', 'case_key': 'SYNTHETIC_KEY', 'dataset_version': 'SYNTHETIC_DATASET', 'image_sha256': hashlib.sha256(image).hexdigest(), 'expected_slice_count': 3}
    (folder / 'case.json').write_text(json.dumps(metadata) + '\n')
    (folder / 'slice_review.csv').write_bytes(b'slice_index,status\r\n0,not_reviewed\r\n1,not_reviewed\r\n2,not_reviewed\r\n')
    (root / 'README.txt').write_text('SYNTHETIC original instructions\n')
    fields = ['case_key', 'participant_id', 'visit_month', 'knee_side', 'expected_slice_count', 'image_sha256', 'relative_folder', 'extra_column']
    row = {k: metadata.get(k, '') for k in fields}
    row.update(relative_folder=folder.relative_to(root).as_posix(), extra_column='unchanged, quoted value')
    with (root / 'case_index.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fields); writer.writeheader(); writer.writerow(row)
    return root, folder


def test_byte_preservation_and_only_index_path_changes(tmp_path):
    source, folder = source_fixture(tmp_path)
    original = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    target = tmp_path / 'new'
    result = migration.migrate(source, target, tmp_path / 'private/record.json', 1)
    migrated = target / 'Cases/OAI_SYNTHETIC_CASE_M072_RIGHT'
    assert {p.name for p in migrated.iterdir()} == set(original)
    assert all((migrated / name).read_bytes() == payload for name, payload in original.items())
    fields, before = migration.read_index(source)
    out_fields, after = migration.read_index(target)
    assert fields == out_fields
    assert all(before[0][k] == after[0][k] for k in fields if k != 'relative_folder')
    assert result['case_files_byte_identical'] == 3
    assert (folder / 'annotations').is_dir()
    assert 'separate local work folder' in (target / 'README.txt').read_text()


def test_nonempty_annotations_preserved_and_rejected_before_output(tmp_path):
    source, folder = source_fixture(tmp_path)
    annotation = folder / 'annotations/precious.txt'
    annotation.write_text('SYNTHETIC existing work')
    with pytest.raises(ValueError, match='annotations_not_empty'):
        migration.migrate(source, tmp_path / 'new', tmp_path / 'record.json')
    assert annotation.read_text() == 'SYNTHETIC existing work'
    assert not (tmp_path / 'new').exists()


def test_duplicate_cases_rejected_before_copy(tmp_path):
    source, _ = source_fixture(tmp_path)
    with (source / 'case_index.csv').open('a') as f:
        with (source / 'case_index.csv').open() as original:
            f.write(original.readlines()[1])
    with pytest.raises(ValueError, match='duplicate'):
        migration.migrate(source, tmp_path / 'new', tmp_path / 'record.json')
    assert not (tmp_path / 'new').exists()


@pytest.mark.parametrize('bad', ['../elsewhere', '/elsewhere', 'Cases\\elsewhere'])
def test_unsafe_paths_rejected(tmp_path, bad):
    source, _ = source_fixture(tmp_path)
    fields, rows = migration.read_index(source)
    rows[0]['relative_folder'] = bad
    with (source / 'case_index.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(rows)
    with pytest.raises((ValueError, FileNotFoundError)):
        migration.migrate(source, tmp_path / 'new', tmp_path / 'record.json')
    assert not (tmp_path / 'new').exists()


def test_source_checksum_mismatch_rejected(tmp_path):
    source, folder = source_fixture(tmp_path)
    (folder / 'image.nii.gz').write_bytes(b'CHANGED SYNTHETIC INPUT')
    with pytest.raises(ValueError, match='checksum'):
        migration.migrate(source, tmp_path / 'new', tmp_path / 'record.json')
    assert not (tmp_path / 'new').exists()


def test_private_record_must_stay_outside_reader_package(tmp_path):
    source, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match='private_record_inside_package'):
        migration.migrate(source, tmp_path / 'new', tmp_path / 'new/private.json')
