"""List completed case files using the package's current index paths.

If an index has not yet been assembled, immutable export reports provide the
original path. Listing does not rewrite reports, reconvert images or accept bytes;
the normal package verifier and copied-byte receipt remain required.
"""
import argparse
import csv
import json
import os
from pathlib import Path
from package_layout import checked_case_contents, verify_relative_folder


def verified_transfer_files(package, reports):
    package, reports = Path(package), Path(reports)
    index = package / 'case_index.csv'
    by_key = None
    if index.exists():
        with index.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        by_key = {row['case_key']: row for row in rows}
        if len(by_key) != len(rows):
            raise ValueError('duplicate_case_index_key')
    output = []
    seen = set()
    for report_path in sorted(reports.glob('*.json')):
        try:
            report = json.loads(report_path.read_text())
        except json.JSONDecodeError:
            continue  # A live exporter may still be writing this private report.
        if not report.get('passed'):
            continue
        selection = report['selection']
        key = selection['case_key']
        if key in seen:
            raise ValueError('duplicate_verified_case_key')
        seen.add(key)
        if by_key is not None:
            if key not in by_key:
                continue
            relative = by_key[key]['relative_folder']
        else:
            relative = selection['relative_folder']
        layout = verify_relative_folder(relative, selection)
        folder = package.joinpath(*relative.split('/'))
        # Refuse even an in-package symlink anywhere along the case path.
        cursor = folder
        while cursor != package:
            if cursor.is_symlink():
                raise ValueError('symlink_in_transfer_path')
            cursor = cursor.parent
        contents = checked_case_contents(folder, layout)
        case = json.loads((folder / 'case.json').read_text())
        if (case['case_key'] != key or case['source_series_key'] != selection['source_series_key']
                or case['image_sha256'] != report['saved_volume']['image_sha256']):
            raise ValueError('transfer_case_source_binding_mismatch')
        for name in ('image.nii.gz', 'case.json', 'slice_review.csv'):
            output.append(relative + '/' + name)
        if 'annotations' in contents:
            output.append(relative + '/annotations/')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(os.environ.get('MRI_PREPARATION_WORKSPACE',str(Path(__file__).resolve().parents[1]))))
    parser.add_argument('--package', type=Path)
    args = parser.parse_args()
    package = args.package or args.workspace / 'staging'
    for relative in verified_transfer_files(package, args.workspace / 'private/verification'):
        print(relative)


if __name__ == '__main__':
    main()
