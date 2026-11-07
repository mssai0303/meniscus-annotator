"""Read-only application-contract validation of a complete correction-job listing.

No WorkStore, annotation, label edit or approval is created. Detailed output must
be written outside the source package; stdout contains aggregate counts only.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib.core import Dataset, ValidationError, read_json, validate_job, within


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--job', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-unresolved', action='store_true')
    args = parser.parse_args()
    dataset = Dataset(args.dataset)
    job_path = args.job or dataset.root / 'correction_job.json'
    job = read_json(job_path)
    report = validate_job(dataset, job, require_full_correction=True, allow_unresolved=args.allow_unresolved)
    report.update(checker='MeniscusAnnotatorLib.core.validate_job', source_files_written_by_checker=False, annotation_work_created=False, real_annotations_edited_or_approved=False)
    if args.output:
        if within(args.output, dataset.root):
            raise ValidationError('Correction validation output must stay outside the source dataset.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('masks', 'unresolved')}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
