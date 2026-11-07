"""Procedural two-case correction package; never reads or searches for MRI."""
import json
from pathlib import Path

import numpy as np

from MeniscusAnnotatorLib import core
from tools.make_synthetic import make_synthetic


def make_correction_synthetic(root, automated=False):
    root = Path(make_synthetic(root, layout='flat'))
    dataset = core.Dataset(root)
    actor_type = 'automated' if automated else 'human_unverified'
    job = {
        'schema_version': 'meniscus_job/1', 'dataset_identity': dataset.identity,
        'protocol': {'version': 'SYNTHETIC-CORRECTION-PRACTICE-1', 'status': 'draft'},
        'practice_context': {'purpose': 'software_practice', 'actor_type': actor_type,
                             'actor': core.PRACTICE_ACTORS[actor_type]}, 'cases': {}}
    for case in dataset.cases:
        nx, ny, nz = case.shape_xyz
        values = np.zeros((nz, ny, nx), dtype=np.uint8)
        # Deliberately geometric patches on acquired planes, not simulated anatomy.
        values[nz // 2, ny // 2 - 3:ny // 2 + 4, nx // 2 - 12:nx // 2 - 5] = 1
        values[nz // 2, ny // 2 - 3:ny // 2 + 4, nx // 2 + 5:nx // 2 + 12] = 2
        path = case.folder / 'starting_mask.nii.gz'
        core.write_native(path, values, case)
        job['cases'][case.key] = {'annotation_mode': 'correction', 'starting_mask': {
            'path': path.relative_to(root).as_posix(), 'sha256': core.sha256(path),
            'source': 'PROCEDURAL GEOMETRIC PHANTOM; NOT A MODEL PREDICTION',
            'version': 'SYNTHETIC-CORRECTION-1'}}
    core.validate_job(dataset, job, require_full_correction=True)
    (root / 'correction_job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    (root / 'README.txt').write_text(
        'SYNTHETIC CORRECTION PRACTICE ONLY. No patient data or anatomical examples.\n'
        'Two full acquired grids, one oblique, with explicit practice-only correction jobs.\n'
        'The coloured rectangles occur on the middle acquired slice.\n'
        'Open this folder through Open dataset. Work and exports stay separately.\n'
        'These outputs cannot be used as research annotations.\n', encoding='utf-8')
    return root
