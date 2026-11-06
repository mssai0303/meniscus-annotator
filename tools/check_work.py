"""Maintained technical checkpoint check; never an anatomical assessment."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import Dataset, WorkStore, ValidationError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--job', help='Original explicit job JSON, if used')
    args = parser.parse_args()
    try:
        dataset = Dataset(args.dataset)
        job = json.loads(Path(args.job).read_text(encoding='utf-8')) if args.job else None
        store = WorkStore(args.work, dataset, job=job)
        reports = []
        for case in dataset.cases:
            for checkpoint in store._checkpoints(store.case_folder(case)):
                store._validate_checkpoint(checkpoint, case)
                reports.append({'case_key':case.key, 'checkpoint':checkpoint.name, 'passed':True})
        print(json.dumps({'scope':'Technical file consistency only; not anatomy or downstream training-loader acceptance.', 'checkpoints':reports, 'passed':True},indent=2))
        return 0
    except (ValidationError, OSError, ValueError) as exc:
        print(json.dumps({'passed':False, 'action':'Restore the original dataset or an intact saved checkpoint.', 'error':str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
