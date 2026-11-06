"""Apply a verified flat-layout migration by moving folders, never rewriting MRI.

An independently verified old-layout backup is required. The journal and mapping
stay outside the reader package. Reopen the dataset in any running application.
"""
import argparse
import datetime
import json
import os
from pathlib import Path, PurePosixPath

from migrate_dataset_layout import digest, inside, require
from preparation.package_layout import CASE_FILES, canonical_relative_folder, checked_case_contents, verify_relative_folder


def safe_path(root, relative):
    require(isinstance(relative, str) and relative and '\\' not in relative, 'unsafe_mapping_path')
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.as_posix() == relative and '..' not in value.parts, 'unsafe_mapping_path')
    result = root / relative
    require(inside(result.resolve(), root.resolve()), 'mapping_path_leaves_package')
    for parent in (result, *result.parents):
        if parent == root:
            break
        require(not parent.is_symlink(), 'mapping_path_contains_symlink')
    return result


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def apply(package, staging, mapping, journal_path):
    package, staging, mapping, journal_path = [Path(p).absolute() for p in (package, staging, mapping, journal_path)]
    require(not journal_path.exists(), 'journal_already_exists')
    require(not inside(journal_path.resolve(), package.resolve()) and not inside(journal_path.resolve(), staging.resolve()), 'journal_inside_package')
    record = json.loads(mapping.read_text(encoding='utf-8'))
    backup = Path(record['source_backup'])
    require(all(p.is_dir() and not p.is_symlink() for p in (package, staging, backup)), 'package_or_backup_missing_or_symlink')
    require(not inside(backup.resolve(), package.resolve()) and not inside(package.resolve(), backup.resolve()), 'backup_overlaps_reader_package')
    require(record['cases'] == len(record['entries']), 'mapping_case_count_mismatch')
    for field in ('old_relative_folder', 'new_relative_folder', 'case_key', 'participant_id', 'source_series_key'):
        require(len({entry[field] for entry in record['entries']}) == record['cases'], 'duplicate_mapping_identity_or_folder')
    expected_files = {'README.txt', 'case_index.csv'}
    expected_dirs = {'Cases'}
    for name in ('README.txt', 'case_index.csv'):
        key = 'readme' if name == 'README.txt' else 'index'
        require(digest(package / name) == record['old_' + key + '_sha256'], 'live_root_metadata_changed')
        require(digest(backup / name) == record['old_' + key + '_sha256'], 'backup_root_metadata_changed')
        require(digest(staging / name) == record['new_' + key + '_sha256'], 'staged_root_metadata_changed')
    for entry in record['entries']:
        old, new = entry['old_relative_folder'], entry['new_relative_folder']
        for root, relative in ((package, old), (package, new), (backup, old), (staging, new)):
            safe_path(root, relative)
        metadata = json.loads((backup / old / 'case.json').read_text(encoding='utf-8'))
        require(verify_relative_folder(old, metadata) == 'legacy' and canonical_relative_folder(metadata, 'flat') == new, 'mapping_identity_mismatch')
        for field in ('case_key', 'participant_id', 'visit_month', 'knee_side', 'source_series_key'):
            require(entry[field] == metadata[field], 'mapping_metadata_identity_changed')
        require(not (package / new).exists(), 'flat_destination_already_exists')
        checked_case_contents(package / old, 'legacy')
        checked_case_contents(backup / old, 'legacy')
        checked_case_contents(staging / new, 'flat')
        require(set(entry['unchanged_files_sha256']) == CASE_FILES, 'mapping_file_schema_invalid')
        for name, expected in entry['unchanged_files_sha256'].items():
            require(all(digest(root / folder / name) == expected for root, folder in ((package, old), (backup, old), (staging, new))), 'case_or_backup_or_stage_changed')
            expected_files.add(old + '/' + name)
        path = Path(old)
        expected_dirs.update(str(p) for p in (path, *path.parents) if str(p) != '.')
        if (package / old / 'annotations').exists():
            expected_dirs.add(old + '/annotations')
    require(not any(p.is_symlink() for p in package.rglob('*')), 'reader_contains_symlink')
    require({str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()} == expected_files, 'unexpected_live_files_preserve_and_investigate')
    require({str(p.relative_to(package)) for p in package.rglob('*') if p.is_dir()} == expected_dirs, 'unexpected_live_directories_preserve_and_investigate')
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = {'schema_version': 'meniscus_layout_apply/1', 'mapping_record': str(mapping), 'package': str(package), 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'phase': 'moving_cases', 'completed_moves': [], 'next_move': None}
    atomic_json(journal_path, journal)
    parents = set()
    try:
        for entry in record['entries']:
            old, new = entry['old_relative_folder'], entry['new_relative_folder']
            journal['next_move'] = {'old_relative_folder': old, 'new_relative_folder': new}
            atomic_json(journal_path, journal)
            source, target = package / old, package / new
            checked_case_contents(source, 'legacy')
            source.rename(target)
            annotations = target / 'annotations'
            if annotations.exists():
                annotations.rmdir()  # Fails safely if any new annotation file appeared.
            checked_case_contents(target, 'flat')
            current = source.parent
            while current != package / 'Cases':
                parents.add(current)
                current = current.parent
            journal['completed_moves'].append(journal['next_move'])
            journal['next_move'] = None
            atomic_json(journal_path, journal)
        for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            parent.rmdir()  # Never remove unknown content recursively.
        journal['phase'] = 'replacing_index_and_readme'
        atomic_json(journal_path, journal)
        for name in ('README.txt', 'case_index.csv'):
            target = package / name
            temporary = package / ('.layout2-' + name + '.tmp')
            with temporary.open('xb') as f:
                f.write((staging / name).read_bytes())
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        journal.update(phase='complete', completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        atomic_json(journal_path, journal)
        return {'phase': 'complete', 'case_folders_moved': len(journal['completed_moves']), 'MRI_rewritten': False, 'top_level_folder_preserved': True}
    except Exception as exc:
        journal.update(phase='interrupted_preserve_and_investigate', error_type=type(exc).__name__)
        atomic_json(journal_path, journal)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('package', 'staging', 'mapping', 'journal'):
        parser.add_argument('--' + field, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(args.package, args.staging, args.mapping, args.journal)))
