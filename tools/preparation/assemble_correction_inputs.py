"""Assemble explicit correction inputs without changing original MRI case files.

Only a new staging package is written. Source images are copied byte-for-byte;
no inference, resampling, annotation, approval or case selection occurs here.
Every indexed case receives an explicit correction rule. An unresolved case has
provenance and a blocking rule, never a fabricated or empty starting mask.
"""
import argparse
import copy
import csv
import datetime
import json
from pathlib import Path
import re
import shutil

from assemble_and_check_package import check_case_schema
from correction_inputs import (IDENTITY_FIELDS, LABEL_MAPPING, READY_FIELDS,
                               canonical, package_relative, validate_correction_package)
from native_mri_package import check_nifti, sha256, need
from package_layout import CASE_FILES, checked_case_contents, verify_relative_folder

VERSION = 'assemble_correction_inputs/1'
PROTOCOL_VERSION = 'meniscus-correction-inputs-draft-1'
COMPATIBLE = 'documented_medial_lateral_assignment'


def outside_repository(path):
    for parent in (path.resolve(), *path.resolve().parents):
        need(not (parent / '.git').exists(), 'dataset_or_private_report_must_be_outside_software_repository')


def read_index(root):
    with (root / 'case_index.csv').open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    need(fields and rows and len(fields) == len(set(fields)), 'invalid_source_case_index')
    need(all(None not in row and all(value is not None for value in row.values()) for row in rows), 'invalid_source_index_row')
    need({'case_key', 'relative_folder', 'participant_id', 'visit_month', 'knee_side', 'image_sha256', 'expected_slice_count'} <= set(fields), 'missing_source_index_identity_fields')
    need(len({row['case_key'] for row in rows}) == len(rows) and len({row['relative_folder'] for row in rows}) == len(rows), 'duplicate_source_case_or_folder')
    return fields, rows


def source_prediction(context):
    value = context.get('source_prediction')
    need(isinstance(value, dict) and all(isinstance(value.get(key), str) and value[key].strip() for key in ('sha256', 'pipeline_version', 'model_version', 'identity')), 'context_source_prediction_provenance_incomplete')
    need(re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is not None, 'context_source_prediction_checksum_invalid')
    return {key: copy.deepcopy(value[key]) for key in ('sha256', 'pipeline_version', 'model_version', 'identity', 'model_sha256') if key in value}


def readable_unresolved_reason(reason):
    if reason == 'existing_pipeline_left_binary_prediction_unsplit_no_medial_lateral_assignment':
        return ('The existing automated prediction is binary and has no documented medial/lateral assignment. '
                'A verified 0/1/2 starting mask is not available for this scan.')
    return reason


def reader_readme(version, total, ready, unresolved):
    text = ('MRI and automated meniscus correction inputs\n'
            f'Dataset: {version}; flat folder layout revision 2. The selected scans are unchanged.\n'
            f'{total} complete MRI scans; {ready} verified starting masks; {unresolved} unresolved ' + ('case.\n' if unresolved == 1 else 'cases.\n'))
    if unresolved:
        text += ('This correction package is INCOMPLETE: each unresolved case is blocked and has no\n'
                 'starting-mask image. Its starting_mask.json explains why. No blank mask was substituted.\n')
    text += ('\nWorkflow: MRI + automated starting mask -> Jeff inspects and corrects -> separate saved work.\n'
             'Open this dataset in the updated application. correction_job.json explicitly specifies\n'
             'correction mode for every case. To choose it manually, use Help -> Annotation setup...\n'
             'and select correction_job.json. Do not use blank mode for this correction package.\n\n'
             'Folders name the actual OAI ID, visit and knee side. M000 is baseline, M072 is month 72,\n'
             'and M096 is month 96; LEFT and RIGHT identify the knee. image.nii.gz contains every\n'
             'acquired MRI slice. case.json and slice_review.csv are unchanged source records.\n'
             'Keep these source files and starting-mask files unchanged during annotation.\n\n'
             'starting_mask.nii.gz is an UNREVIEWED automated prediction on the complete acquired MRI grid.\n'
             'Labels: 0 = no predicted meniscus; 1 = medial meniscus; 2 = lateral meniscus.\n'
             'Zero is not expert-confirmed background. Missing tissue and false positives still need review.\n'
             'Nearest-neighbour mapping to the MRI grid may change sampled boundaries; provenance is in\n'
             'starting_mask.json. No additional smoothing, filling or fragment removal was applied.\n\n'
             'The application saves drafts in a separate local work folder and approved exports in a\n'
             'separate results folder. Use a separate correction work folder, not earlier blank/practice work.\n'
             'Do not save annotation work inside this source dataset. Annotations have not yet been completed.\n'
             'Original case and slice-review statuses remain not_started / not_reviewed.\n')
    return text


def assemble(source, prepared, contexts, output, private_report, expected_cases=None, protocol_version=PROTOCOL_VERSION):
    source, prepared, output, private_report = [Path(path).absolute() for path in (source, prepared, output, private_report)]
    need(source.is_dir() and prepared.is_dir() and not source.is_symlink() and not prepared.is_symlink(), 'source_or_prepared_tree_missing_or_symlink')
    need(not output.exists() and not private_report.exists(), 'assembly_output_already_exists_preserve_and_inspect')
    need(not output.resolve().is_relative_to(source.resolve()) and not source.resolve().is_relative_to(output.resolve()), 'source_output_overlap')
    need(not output.resolve().is_relative_to(prepared.resolve()) and not prepared.resolve().is_relative_to(output.resolve()), 'prepared_output_overlap')
    need(not private_report.resolve().is_relative_to(output.resolve()) and not private_report.resolve().is_relative_to(source.resolve()), 'private_report_inside_reader_package')
    need(not private_report.resolve().is_relative_to(prepared.resolve()), 'private_report_inside_prepared_input_tree')
    outside_repository(output); outside_repository(private_report)
    need(isinstance(protocol_version, str) and protocol_version.strip(), 'explicit_draft_protocol_version_required')
    fields, rows = read_index(source)
    need(expected_cases is None or len(rows) == expected_cases, 'source_case_count_mismatch')
    need(isinstance(contexts, list), 'private_contexts_must_be_list')
    contexts_by_key = {item['case_key']: item for item in contexts}
    need(len(contexts_by_key) == len(contexts) and set(contexts_by_key) == {row['case_key'] for row in rows}, 'context_membership_mismatch_or_duplicates')
    index_hash = sha256(source / 'case_index.csv')
    case_files, prepared_files, cases, plans = {}, {}, [], []
    versions, pipeline_versions, model_versions = set(), set(), set()
    for row in rows:
        relative, key = row['relative_folder'], row['case_key']
        folder = package_relative(source, relative)
        case = json.loads((folder / 'case.json').read_text(encoding='utf-8'))
        need(verify_relative_folder(relative, case) == 'flat', 'correction_assembly_requires_existing_flat_package')
        checked_case_contents(folder, 'flat')
        affine = check_case_schema(case)
        need(case['annotation_status'] == 'not_started', 'source_annotation_status_changed')
        for field in ('case_key', 'participant_id', 'knee_side', 'image_sha256'):
            need(str(case[field]) == str(row[field]), 'source_index_metadata_identity_mismatch')
        need(int(row['visit_month']) == case['visit_month'] and int(row['expected_slice_count']) == case['expected_slice_count'], 'source_index_visit_or_slice_mismatch')
        context_row = contexts_by_key[key]
        need(context_row.get('relative_folder') == relative, 'context_folder_mismatch')
        context = context_row.get('context')
        need(isinstance(context, dict) and all(context.get(field) == case[field] for field in (*IDENTITY_FIELDS, 'knee_side')), 'context_case_source_identity_mismatch')
        prediction = source_prediction(context)
        pipeline_versions.add(prediction['pipeline_version']);model_versions.add(prediction['model_version'])
        for name in sorted(CASE_FILES):
            case_files[relative + '/' + name] = sha256(folder / name)
        need(case_files[relative + '/image.nii.gz'] == case['image_sha256'], 'source_MRI_checksum_mismatch')
        check_nifti(folder / 'image.nii.gz', case['dimensions_xyz'], affine)
        with (folder / 'slice_review.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream); review = list(reader)
            need(reader.fieldnames == ['slice_index', 'status'] and [r['slice_index'] for r in review] == [str(k) for k in range(case['expected_slice_count'])] and all(r['status'] == 'not_reviewed' for r in review), 'source_slice_review_changed')
        compatibility = context_row.get('categorical_compatibility')
        if compatibility == COMPATIBLE:
            input_folder = package_relative(prepared, relative)
            need(input_folder.is_dir() and {p.name for p in input_folder.iterdir()} == {'starting_mask.nii.gz', 'starting_mask.json'}, 'compatible_case_prepared_files_missing_or_unexpected')
            need(not any(p.is_symlink() for p in input_folder.iterdir()), 'prepared_case_contains_symlink')
            metadata = json.loads((input_folder / 'starting_mask.json').read_text(encoding='utf-8'))
            need(set(metadata) == READY_FIELDS and metadata.get('status') == 'unreviewed_automated_prediction', 'prepared_sidecar_schema_or_status_invalid')
            need(all(metadata.get(field) == case[field] for field in IDENTITY_FIELDS), 'prepared_sidecar_case_binding_mismatch')
            need(metadata.get('label_mapping') == LABEL_MAPPING, 'prepared_sidecar_label_mapping_invalid')
            need(all(metadata['source_prediction'].get(field) == prediction[field] for field in ('sha256', 'pipeline_version', 'model_version')), 'prepared_prediction_version_or_checksum_mismatch')
            need(sha256(input_folder / 'starting_mask.nii.gz') == metadata.get('prepared_mask_sha256'), 'prepared_mask_checksum_mismatch')
            for name in ('starting_mask.nii.gz', 'starting_mask.json'):
                prepared_files[relative + '/' + name] = sha256(input_folder / name)
            rule = {'annotation_mode': 'correction', 'availability': 'ready',
                    'starting_mask': {'path': relative + '/starting_mask.nii.gz', 'sha256': metadata['prepared_mask_sha256'],
                                      'source': prediction['identity'] + '; unreviewed automated IWFS prediction',
                                      'version': prediction['pipeline_version']}}
        elif compatibility == 'unresolved':
            unresolved_folder = package_relative(prepared, relative)
            need(not unresolved_folder.exists() or (unresolved_folder.is_dir() and not any(unresolved_folder.iterdir())), 'unresolved_case_has_unexpected_prepared_content')
            reason = context_row.get('unresolved_reason')
            need(isinstance(reason, str) and reason.strip(), 'unresolved_reason_required')
            reason = readable_unresolved_reason(reason)
            metadata = {'schema_version': 'meniscus_starting_mask/1', **{field: case[field] for field in IDENTITY_FIELDS},
                        'status': 'unresolved', 'reason': reason, 'source_prediction': prediction,
                        'verification': {'status': 'unresolved', 'scope': 'No categorical anatomical assignment is established for this existing prediction; no mask image or expert annotation was fabricated.'}}
            rule = {'annotation_mode': 'correction', 'availability': 'unresolved', 'reason': reason, 'starting_mask': None}
        else:
            need(False, 'unsupported_context_status_no_blank_or_missing_mask_fallback')
        versions.add(case['dataset_version']);cases.append(case)
        plans.append({'relative': relative, 'case': case, 'ready': compatibility == COMPATIBLE, 'sidecar': metadata, 'rule': rule})
    need(len(versions) == len(pipeline_versions) == len(model_versions) == 1, 'mixed_dataset_pipeline_or_model_versions')
    need(len({case['participant_id'] for case in cases}) == len(cases) and len({case['source_series_key'] for case in cases}) == len(cases) and len({case['series_instance_uid'] for case in cases}) == len(cases), 'duplicate_source_participant_or_acquisition')
    dataset_identity = canonical(sorted((case['case_key'], canonical(case)) for case in cases))
    output.mkdir(parents=True)
    for plan in plans:
        relative = plan['relative']; target = output / relative;target.mkdir(parents=True)
        for name in sorted(CASE_FILES):
            shutil.copy2(source / relative / name, target / name)
            need(sha256(target / name) == case_files[relative + '/' + name], 'copied_original_case_file_changed')
        if plan['ready']:
            for name in ('starting_mask.nii.gz', 'starting_mask.json'):
                shutil.copy2(prepared / relative / name, target / name)
                need(sha256(target / name) == prepared_files[relative + '/' + name], 'copied_prepared_file_changed')
        else:
            (target / 'starting_mask.json').write_text(json.dumps(plan['sidecar'], indent=2) + '\n', encoding='utf-8')
    shutil.copy2(source / 'case_index.csv', output / 'case_index.csv')
    need(sha256(output / 'case_index.csv') == index_hash, 'case_index_bytes_changed')
    ready = sum(plan['ready'] for plan in plans);unresolved = len(plans) - ready
    (output / 'README.txt').write_text(reader_readme(next(iter(versions)), len(cases), ready, unresolved), encoding='utf-8')
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': dataset_identity,
           'protocol': {'version': protocol_version, 'status': 'draft'},
           'cases': {plan['case']['case_key']: plan['rule'] for plan in plans}}
    (output / 'correction_job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    catalog = {row['case_key']: row for row in rows};layouts = {key: 'flat' for key in catalog}
    summary, extras = validate_correction_package(output, cases, catalog, layouts, allow_unresolved=True)
    need(summary['prepared_masks'] == ready and summary['unresolved_cases'] == unresolved, 'assembly_validation_counts_mismatch')
    expected_files = set(case_files) | extras | {'README.txt', 'case_index.csv'}
    need({str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()} == expected_files, 'assembled_package_file_set_mismatch')
    need(sha256(source / 'case_index.csv') == index_hash, 'source_case_index_changed_during_assembly')
    for relative, expected in case_files.items():
        need(sha256(source / relative) == expected, 'original_case_file_changed_during_assembly')
    summary.update(missing_cases=0, original_case_files_preserved=len(case_files), original_index_byte_identical=True,
                   annotations_completed=False, source_dataset_version=next(iter(versions)))
    result = {'schema_version': VERSION, 'assembled_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'summary': summary, 'source_package': str(source), 'prepared_tree': str(prepared), 'staging_package': str(output),
              'source_case_index_sha256': index_hash, 'source_case_files_sha256': case_files,
              'prepared_source_files_sha256': prepared_files, 'correction_job_sha256': sha256(output / 'correction_job.json'),
              'reader_README_sha256': sha256(output / 'README.txt'),
              'scope': 'Explicit unreviewed automated correction inputs only. No real annotation, approval, inference, MRI conversion, or case selection.'}
    private_report.parent.mkdir(parents=True, exist_ok=True)
    with private_report.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2);stream.write('\n')
    private_report.chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('source', 'prepared', 'contexts', 'output', 'private-report'):
        parser.add_argument('--' + option, required=True, type=Path)
    parser.add_argument('--expected-cases', type=int)
    parser.add_argument('--protocol-version', default=PROTOCOL_VERSION)
    args = parser.parse_args()
    result = assemble(args.source, args.prepared, json.loads(args.contexts.read_text(encoding='utf-8')), args.output, args.private_report, args.expected_cases, args.protocol_version)
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
