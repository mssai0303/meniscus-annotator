"""Procedural, non-anatomical fixtures for the Draw interaction matrix.

Eight explicit metadata/physical-geometry combinations are generated outside the
repository. Neither knee side nor compartment identity is inferred from an
array index, filename or screen side. The two physical slice directions cover
the same physical volume by reversing I and K together (a right-handed frame).
"""
import csv
import json
from pathlib import Path

import nibabel as nib
import numpy as np

from MeniscusAnnotatorLib.core import (Dataset, INDEX_FIELDS, SLICE_CONVENTION,
                                     case_folder_options, sha256, write_native)


def make_draw_matrix(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    rows, truth = [], {}
    spacing = np.array([.37, .43, 2.8])
    origin = np.array([-44., -33., -18.])
    base_direction = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    for side in ('L', 'R'):
        for reverse in (False, True):
            for oblique in (False, True):
                key = 'SYNTH_DRAW_%s_%s_%s' % (side, 'NEG' if reverse else 'POS',
                                               'OBLIQUE' if oblique else 'REGULAR')
                shape = (96, 80, 11 if oblique else 9)
                direction = base_direction.copy()
                if oblique:
                    a, b = np.deg2rad([17., -9.])
                    rz = np.array([[np.cos(a), -np.sin(a), 0],
                                   [np.sin(a), np.cos(a), 0], [0, 0, 1]])
                    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0],
                                   [-np.sin(b), 0, np.cos(b)]])
                    direction = rz @ ry @ direction
                base_lps = np.eye(4)
                base_lps[:3, :3] = direction @ np.diag(spacing)
                base_lps[:3, 3] = origin
                base_ras = np.diag([-1, -1, 1, 1]) @ base_lps
                x, y, z = np.indices(shape)
                radius = ((x - 47.5) / 40.) ** 2 + ((y - 39.5) / 34.) ** 2
                signal = (400 * np.exp(-radius * 2)
                          + 150 * np.exp(-((radius - .55) / .07) ** 2)
                          + 35 * z / (shape[2] - 1)).astype(np.int16)
                labels = np.zeros(shape, dtype=np.uint8)
                labels[22:29, 24:31, 2:4] = 1
                labels[62:69, 48:55, 5:7] = 2
                actual_origin = origin.copy()
                if reverse:
                    actual_origin += (direction[:, 0] * spacing[0] * (shape[0] - 1)
                                      + direction[:, 2] * spacing[2] * (shape[2] - 1))
                    direction = direction @ np.diag([-1., 1., -1.])
                    signal = signal[::-1, :, ::-1].copy()
                    labels = labels[::-1, :, ::-1].copy()
                lps = np.eye(4)
                lps[:3, :3] = direction @ np.diag(spacing)
                lps[:3, 3] = actual_origin
                ras = np.diag([-1, -1, 1, 1]) @ lps
                metadata = {
                    'schema_version': 'meniscus_case/1',
                    'dataset_version': 'SYNTHETIC_DRAW_MATRIX_v1',
                    'case_key': key, 'participant_id': 'SYNTH%02d' % (len(rows) + 1), 'visit_month': 0,
                    'original_visit_code': 'SYNTHETIC', 'source_visit_label': 'SYNTHETIC',
                    'knee_side': side, 'sequence': 'sagittal IW fat-suppressed TSE',
                    'source_series_key': key, 'series_instance_uid': 'SYNTHETIC-UID-' + key,
                    'archive_series_number': 'SYNTHETIC', 'dicom_series_number': 'SYNTHETIC',
                    'source_study_date': 'SYNTHETIC',
                    'source_series_description': 'SYNTHETIC GEOMETRIC PHANTOM; NOT PATIENT DATA',
                    'dimensions_xyz': list(shape), 'spacing_xyz_mm': spacing.tolist(),
                    'origin_lps_mm': actual_origin.tolist(),
                    'direction_lps_columns': direction.tolist(),
                    'expected_slice_count': shape[2], 'slice_index_convention': SLICE_CONVENTION,
                    'annotation_status': 'not_started',
                    'preparation_verifier': 'synthetic-draw-matrix/1; no anatomical claims'}
                folder = root / case_folder_options(metadata)[0]
                folder.mkdir(parents=True)
                image = nib.Nifti1Image(signal, ras)
                image.header.set_xyzt_units('mm')
                image.set_qform(ras, 1)
                image.set_sform(ras, 1)
                nib.save(image, folder / 'image.nii.gz')
                metadata['image_sha256'] = sha256(folder / 'image.nii.gz')
                (folder / 'case.json').write_text(json.dumps(metadata, indent=2) + '\n')
                with (folder / 'slice_review.csv').open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=['slice_index', 'status'])
                    writer.writeheader()
                    writer.writerows({'slice_index': k, 'status': 'not_reviewed'}
                                     for k in range(shape[2]))
                rows.append({field: {'relative_folder': folder.relative_to(root).as_posix()}.get(
                    field, metadata.get(field, '')) for field in INDEX_FIELDS})

                def actual_ijk(point):
                    i, j, k = point
                    return [shape[0] - 1 - i, j, shape[2] - 1 - k] if reverse else list(point)

                medial = (25, 27, 3)
                lateral = (65, 51, 6)
                truth[key] = {'side': side, 'participant_id': metadata['participant_id'],
                              'reverse': reverse, 'oblique': oblique,
                              'shape_xyz': list(shape), 'affine_ras': ras.tolist(),
                              'medial_seed_ijk': actual_ijk(medial),
                              'lateral_seed_ijk': actual_ijk(lateral),
                              'medial_seed_ras_mm': (base_ras @ [*medial, 1])[:3].tolist(),
                              'lateral_seed_ras_mm': (base_ras @ [*lateral, 1])[:3].tolist(),
                              'mask_array_ijk': labels}
    with (root / 'case_index.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (root / 'README.txt').write_text(
        'SYNTHETIC SOFTWARE TEST ONLY. Eight geometric phantoms, not knee anatomy.\n')
    dataset = Dataset(root)
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': dataset.identity,
           'protocol': {'version': 'SYNTHETIC-DRAW-MATRIX-SOFTWARE-1', 'status': 'draft'},
           'practice_context': {'purpose': 'software_practice', 'actor_type': 'automated',
                                'actor': 'Software QA (automated)'}, 'cases': {}}
    for case in dataset.cases:
        item = truth[case.key]
        mask = case.folder / 'starting_mask.nii.gz'
        write_native(mask, item.pop('mask_array_ijk').transpose(2, 1, 0), case)
        job['cases'][case.key] = {
            'annotation_mode': 'correction',
            'starting_mask': {'path': mask.relative_to(root).as_posix(),
                              'source': 'SYNTHETIC KNOWN GEOMETRY; NOT A MODEL OR ANATOMY',
                              'version': 'synthetic-draw-matrix/1', 'sha256': sha256(mask)}}
    (root / 'correction_job.json').write_text(json.dumps(job, indent=2) + '\n')
    (root / 'synthetic_truth.json').write_text(json.dumps(truth, indent=2) + '\n')
    return dataset, truth
