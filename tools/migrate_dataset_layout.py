"""Copy a verified input package to flat folders without changing case-file bytes.

Run against a recoverable backup, with destination and private record outside
the software repository. This tool never edits its source or any annotation.
"""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from preparation.package_layout import CASE_FILES, canonical_relative_folder, checked_case_contents, verify_relative_folder


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inside(path, parent):
    return path == parent or parent in path.parents


def read_index(root):
    with (root / 'case_index.csv').open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    require(fields and len(fields) == len(set(fields)) and rows, 'invalid_index')
    require({'participant_id', 'case_key', 'relative_folder', 'visit_month', 'knee_side', 'expected_slice_count', 'image_sha256'} <= set(fields), 'missing_index_identity')
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), 'invalid_index_row')
    return fields, rows


def readme(version, count):
    return (
        'OAI knee MRI annotation inputs\n'
        f'Dataset: {version}\n'
        f'{count} complete scans from {count} different participants.\n'
        'Folder layout revision 2 (flat case folders); the scans and dataset identity are unchanged.\n\n'
        'Each folder is named OAI_<ID>_M<month>_<side>. ID is the actual OAI participant ID.\n'
        'M000 means baseline, M072 means month 72, and M096 means month 96.\n'
        'LEFT and RIGHT identify the knee.\n\n'
        'image.nii.gz contains the complete acquired MRI scan, including every acquired slice.\n'
        'case.json identifies its original acquisition. slice_review.csv is the original slice list.\n'
        'Keep these source files unchanged during annotation. Do not crop, resize, resample or replace them.\n\n'
        'The application saves drafts in a separate local work folder and approved exports\n'
        'in a separate results folder. Do not save annotation work in these source folders.\n'
        'Annotations have not yet been completed. Reorganising the folders adds no annotations.\n'
    )


def migrate(source, destination, record, expected_count=None, require_oai=False):
    source, destination, record = [Path(p).absolute() for p in (source, destination, record)]
    require(source.is_dir() and not source.is_symlink(), 'source_missing_or_symlink')
    require(not destination.exists(), 'destination_already_exists')
    require(not inside(destination.resolve(), source.resolve()) and not inside(source.resolve(), destination.resolve()), 'source_destination_overlap')
    require(not inside(record.resolve(), destination.resolve()) and not inside(record.resolve(), source.resolve()), 'private_record_inside_package')
    require(not record.exists(), 'migration_record_already_exists')
    fields, rows = read_index(source)
    require(expected_count is None or len(rows) == expected_count, 'case_count_mismatch')
    seen = {name: set() for name in ('folder', 'case', 'participant', 'source', 'uid')}
    entries, versions, source_files, source_layouts = [], set(), {'README.txt', 'case_index.csv'}, set()
    # Validate every source and target name before creating any output folder.
    for row in rows:
        relative = row['relative_folder']
        spelling = PurePosixPath(relative)
        require(relative and '\\' not in relative and not spelling.is_absolute() and spelling.as_posix() == relative and '..' not in spelling.parts, 'unsafe_source_path')
        path = source / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(source.resolve()), 'unsafe_source_path')
        for parent in (path, *path.parents):
            if parent == source:
                break
            require(not parent.is_symlink(), 'source_parent_symlink')
        metadata = json.loads((path / 'case.json').read_text(encoding='utf-8'))
        layout = verify_relative_folder(relative, metadata)
        checked_case_contents(path, layout)
        source_layouts.add(layout)
        new_relative = canonical_relative_folder(metadata, 'flat')
        for field in ('participant_id', 'case_key', 'knee_side', 'image_sha256'):
            require(row[field] == str(metadata[field]), 'index_metadata_identity_mismatch')
        require(int(row['visit_month']) == metadata['visit_month'] and int(row['expected_slice_count']) == metadata['expected_slice_count'], 'index_visit_or_slice_mismatch')
        if require_oai:
            require(bool(re.fullmatch(r'\d{7}', metadata['participant_id'])) and metadata['visit_month'] in (0, 72, 96), 'unexpected_oai_identity_or_visit')
        identities = {'folder': new_relative, 'case': metadata['case_key'], 'participant': metadata['participant_id'], 'source': metadata['source_series_key'], 'uid': metadata['series_instance_uid']}
        for kind, value in identities.items():
            require(value and value not in seen[kind], 'duplicate_' + kind)
            seen[kind].add(value)
        hashes = {name: digest(path / name) for name in sorted(CASE_FILES)}
        require(hashes['image.nii.gz'] == metadata['image_sha256'], 'source_image_checksum_mismatch')
        source_files.update(relative + '/' + name for name in CASE_FILES)
        versions.add(metadata['dataset_version'])
        entries.append({'case_key': metadata['case_key'], 'participant_id': metadata['participant_id'], 'visit_month': metadata['visit_month'], 'knee_side': metadata['knee_side'], 'source_series_key': metadata['source_series_key'], 'old_relative_folder': relative, 'new_relative_folder': new_relative, 'unchanged_files_sha256': hashes})
    require(len(versions) == 1 and len(source_layouts) == 1, 'mixed_dataset_versions_or_layouts')
    require({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} == source_files, 'unexpected_source_files_preserve_and_investigate')
    require(not any(p.is_symlink() for p in source.rglob('*')), 'source_contains_symlink')
    source_index_hash = digest(source / 'case_index.csv')
    source_readme_hash = digest(source / 'README.txt')
    destination.mkdir(parents=True)
    for row, entry in zip(rows, entries):
        output = destination / entry['new_relative_folder']
        output.mkdir(parents=True)
        for name, expected in entry['unchanged_files_sha256'].items():
            shutil.copy2(source / entry['old_relative_folder'] / name, output / name)
            require(digest(output / name) == expected, 'copied_case_file_changed')
        row['relative_folder'] = entry['new_relative_folder']
    with (destination / 'case_index.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (destination / 'README.txt').write_text(readme(next(iter(versions)), len(rows)), encoding='utf-8')
    out_fields, out_rows = read_index(destination)
    old_fields, old_rows = read_index(source)
    require(fields == out_fields == old_fields, 'index_columns_changed')
    for before, after, entry in zip(old_rows, out_rows, entries):
        require(all(before[k] == after[k] for k in fields if k != 'relative_folder'), 'nonpath_index_value_changed')
        require(after['relative_folder'] == entry['new_relative_folder'], 'index_reference_mismatch')
        checked_case_contents(destination / after['relative_folder'], 'flat')
    require(digest(source / 'case_index.csv') == source_index_hash and digest(source / 'README.txt') == source_readme_hash, 'source_changed_during_migration')
    result = {'schema_version': 'meniscus_layout_migration/1', 'layout_revision': 2, 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source_backup': str(source), 'destination_staging': str(destination), 'dataset_version': next(iter(versions)), 'cases': len(rows), 'unique_participants': len(seen['participant']), 'case_files_byte_identical': len(entries) * 3, 'old_index_sha256': source_index_hash, 'new_index_sha256': digest(destination / 'case_index.csv'), 'old_readme_sha256': source_readme_hash, 'new_readme_sha256': digest(destination / 'README.txt'), 'all_nonpath_index_columns_unchanged': True, 'case_identities_and_metadata_unchanged': True, 'entries': entries}
    record.parent.mkdir(parents=True, exist_ok=True)
    with record.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    record.chmod(0o600)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'destination', 'record'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--expected-count', type=int)
    parser.add_argument('--require-oai', action='store_true')
    args = parser.parse_args()
    result = migrate(args.source, args.destination, args.record, args.expected_count, args.require_oai)
    print(json.dumps({key: value for key, value in result.items() if key != 'entries'}))
