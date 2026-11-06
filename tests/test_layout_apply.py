"""In-place folder moves preserve source bytes and the recoverable backup."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest
from test_layout_migration import source_fixture, migration, TOOLS

spec = importlib.util.spec_from_file_location('apply_dataset_layout', TOOLS / 'apply_dataset_layout.py')
applying = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applying)


def setup_migration(tmp_path):
    live, old_folder = source_fixture(tmp_path)
    backup = tmp_path / 'private/backup'
    shutil.copytree(live, backup)
    staging = tmp_path / 'flat'
    record = tmp_path / 'private/mapping.json'
    mapping = migration.migrate(backup, staging, record, 1)
    return live, old_folder, backup, staging, record, mapping


def test_apply_moves_without_rewriting_case_files_or_top_level(tmp_path):
    live, old, backup, staging, record, mapping = setup_migration(tmp_path)
    inode = live.stat().st_ino
    before = {name: (old / name).read_bytes() for name in migration.CASE_FILES}
    result = applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    new = live / mapping['entries'][0]['new_relative_folder']
    assert result['case_folders_moved'] == 1 and not result['MRI_rewritten']
    assert live.stat().st_ino == inode and not old.exists()
    assert {p.name for p in (live / 'Cases').iterdir()} == {new.name}
    assert {p.name for p in new.iterdir()} == set(before)
    assert all((new / name).read_bytes() == value for name, value in before.items())
    assert (backup / mapping['entries'][0]['old_relative_folder'] / 'annotations').is_dir()


def test_apply_refuses_new_annotation_work_before_moves(tmp_path):
    live, old, backup, staging, record, _ = setup_migration(tmp_path)
    annotation = old / 'annotations/SYNTHETIC-work.txt'
    annotation.write_text('do not remove')
    with pytest.raises(ValueError, match='annotations_not_empty'):
        applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    assert annotation.read_text() == 'do not remove' and not (tmp_path / 'private/journal.json').exists()


def test_apply_refuses_changed_live_image(tmp_path):
    live, old, backup, staging, record, _ = setup_migration(tmp_path)
    (old / 'image.nii.gz').write_bytes(b'CHANGED SYNTHETIC PAYLOAD')
    with pytest.raises(ValueError, match='changed'):
        applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    assert old.exists() and not (tmp_path / 'private/journal.json').exists()


@pytest.mark.parametrize('bad', ['/outside', '../outside', 'Cases\\outside'])
def test_apply_refuses_invalid_mapping_paths(tmp_path, bad):
    live, old, backup, staging, record, value = setup_migration(tmp_path)
    value['entries'][0]['new_relative_folder'] = bad
    record.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='mapping_path'):
        applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    assert old.exists() and not (tmp_path / 'private/journal.json').exists()


def test_apply_refuses_duplicate_mapping_before_moves(tmp_path):
    live, old, backup, staging, record, value = setup_migration(tmp_path)
    value['entries'].append(value['entries'][0]);value['cases'] = 2
    record.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='duplicate_mapping'):
        applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    assert old.exists()


def test_apply_refuses_extra_live_files(tmp_path):
    live, old, backup, staging, record, _ = setup_migration(tmp_path)
    extra = live / 'do-not-delete.txt';extra.write_text('preserve')
    with pytest.raises(ValueError, match='unexpected_live_files'):
        applying.apply(live, staging, record, tmp_path / 'private/journal.json')
    assert extra.read_text() == 'preserve' and old.exists()
