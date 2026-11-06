#!/usr/bin/env python3
"""Create visibly synthetic, non-anatomical test volumes. Never uses participant data."""
import argparse
import csv
import json
from pathlib import Path
import sys

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib.core import INDEX_FIELDS, SLICE_CONVENTION, sha256


def make_synthetic(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'case_index.csv').exists():
        raise ValueError('Synthetic destination already contains a dataset; choose a new empty folder.')
    rows = []
    for index, shape in enumerate(((96, 80, 17), (112, 88, 23))):
        key = 'SYNTHETIC_%02d' % (index+1)
        folder = root / 'Cases' / ('OAI_' + key) / 'M000' / 'LEFT' / ('series_' + key)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'annotations').mkdir()
        direction = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
        if index:
            a, b = np.deg2rad([13., 6.])
            rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
            ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
            direction = rz @ ry @ direction
        spacing = np.array([.36, .41, 3.])
        origin = np.array([-42., -30., -23.])
        lps = np.eye(4)
        lps[:3, :3] = direction @ np.diag(spacing)
        lps[:3, 3] = origin
        ras = np.diag([-1, -1, 1, 1]) @ lps
        x, y, z = np.indices(shape)
        r = ((x-(shape[0]-1)/2)/(shape[0]*.42))**2 + ((y-(shape[1]-1)/2)/(shape[1]*.42))**2
        slab = np.maximum(0, 1 - ((z-(shape[2]-1)/2)/(shape[2]*.65))**2)
        signal = (260 * np.exp(-r*2) + 130*np.exp(-((r-.55)/.08)**2)) * slab
        # Known geometric landmarks, not anatomical menisci. Fixed seed.
        signal += 120*((x-shape[0]*.42)**2+(y-shape[1]*.45)**2 < 60)
        signal += np.random.default_rng(612+index).normal(0, 7, shape)
        image = nib.Nifti1Image(np.clip(signal, 0, 1000).astype(np.int16), ras)
        image.header.set_xyzt_units('mm')
        image.set_qform(ras, 1)
        image.set_sform(ras, 1)
        nib.save(image, folder / 'image.nii.gz')
        metadata = {'schema_version': 'meniscus_case/1', 'dataset_version': 'SYNTHETIC_PRACTICE_v1',
                    'case_key': key, 'participant_id': key, 'visit_month': 0,
                    'original_visit_code': 'SYNTHETIC', 'source_visit_label': 'SYNTHETIC',
                    'knee_side': 'L', 'sequence': 'sagittal IW fat-suppressed TSE',
                    'source_series_key': key, 'series_instance_uid': 'SYNTHETIC-UID-' + key,
                    'archive_series_number': 'SYNTHETIC', 'dicom_series_number': 'SYNTHETIC',
                    'source_study_date': 'SYNTHETIC', 'source_series_description': 'SYNTHETIC GEOMETRIC PHANTOM — NOT PATIENT DATA',
                    'dimensions_xyz': list(shape), 'spacing_xyz_mm': spacing.tolist(),
                    'origin_lps_mm': origin.tolist(), 'direction_lps_columns': direction.tolist(),
                    'expected_slice_count': shape[2], 'slice_index_convention': SLICE_CONVENTION,
                    'image_sha256': sha256(folder / 'image.nii.gz'), 'annotation_status': 'not_started',
                    'preparation_verifier': 'synthetic-generator/1; not DICOM verified'}
        (folder / 'case.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        with (folder / 'slice_review.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=['slice_index', 'status'])
            writer.writeheader()
            writer.writerows({'slice_index': k, 'status': 'not_reviewed'} for k in range(shape[2]))
        rows.append({k: {'relative_folder': folder.relative_to(root).as_posix()}.get(k, metadata[k] if k in metadata else '') for k in INDEX_FIELDS})
    with (root / 'case_index.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (root / 'README.txt').write_text('SYNTHETIC PRACTICE ONLY. Geometric phantoms, not anatomical scans or participant records.\nTwo acquired grids: axis-aligned and oblique.\n', encoding='utf-8')
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(make_synthetic(args.output))
