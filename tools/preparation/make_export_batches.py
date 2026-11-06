"""Freeze source-bound batches for a supplied fixed selection; never reselect.

New output folders use layout revision 2. Existing batch files and receipts must
remain immutable; this command refuses to overwrite them. It does not read MRI.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from package_layout import canonical_relative_folder


def freeze_batches(workspace, selection, technical_subset, dataset_version):
    workspace, selection, technical_subset = map(Path, (workspace, selection, technical_subset))
    with selection.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 250 or len({row['participant_id'] for row in rows}) != 250:
        raise ValueError('expected_250_unique_participants')
    selected = []
    for row in rows:
        bound = dict(row, expected_slice_count=int(row['native_slices_recorded']),
                     original_visit_code=row['archive_visit_folder'], dataset_version=dataset_version)
        bound['relative_folder'] = canonical_relative_folder(bound, 'flat')
        selected.append(bound)
    if len({row['relative_folder'] for row in selected}) != len(selected):
        raise ValueError('duplicate_case_folder')
    with technical_subset.open(newline='') as stream:
        technical = {row['case_key'] for row in csv.DictReader(stream)}
    subset = [row for row in selected if row['case_key'] in technical]
    if len(subset) != 6 or not all(row['dataset_role_working'] == 'training' and row['practice_reserved'] == 'true' for row in subset):
        raise ValueError('technical_subset_not_six_reserved_development_cases')
    batches = {'development': subset, 'remaining': [row for row in selected if row not in subset]}
    targets = {name: workspace / 'private' / ('batch_' + name + '.json') for name in batches}
    receipt = workspace / 'results/export_batch_freeze.json'
    if any(path.exists() for path in [*targets.values(), receipt]):
        raise FileExistsError('Existing frozen batch or receipt must not be overwritten.')
    for path in [*targets.values(), receipt]:
        path.parent.mkdir(parents=True, exist_ok=True)
    for name, batch in batches.items():
        with targets[name].open('x') as stream:
            json.dump(batch, stream, indent=2); stream.write('\n')
        targets[name].chmod(0o600)
    record = {'selection_sha256': hashlib.sha256(selection.read_bytes()).hexdigest(),
              'folder_layout': 'flat',
              'batches': {name: {'cases': len(batch), 'sha256': hashlib.sha256(targets[name].read_bytes()).hexdigest()} for name, batch in batches.items()},
              'expected_uncompressed_selected_pixel_bytes': sum(int(row['native_slices_recorded']) * int(row['native_rows_recorded']) * int(row['native_columns_recorded']) * 2 for row in selected),
              'note': 'Supplied fixed selection only; no sampling, image read, conversion or annotation.'}
    with receipt.open('x') as stream:
        json.dump(record, stream, indent=2); stream.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--technical-subset', type=Path, required=True)
    parser.add_argument('--dataset-version', required=True)
    args = parser.parse_args()
    print(json.dumps(freeze_batches(args.workspace, args.selection, args.technical_subset, args.dataset_version)))


if __name__ == '__main__':
    main()
