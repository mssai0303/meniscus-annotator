"""Synthetic physical-grid evidence for correction-input conversion, not anatomy."""
import gzip
import json
from pathlib import Path
import struct

import numpy as np
import pytest
import SimpleITK as sitk

from prepare_starting_mask import (StartingMaskError, affine_lps, counts, label_existing_binary,
                                   physical_nearest, prepare, sha256)


def write_image(path, array, origin, direction, spacing):
    image = sitk.GetImageFromArray(array)
    image.SetOrigin(origin)
    image.SetDirection(tuple(direction.ravel()))
    image.SetSpacing(spacing)
    sitk.WriteImage(image, str(path), True)
    return image


def fixture(tmp_path, side='R', tilt=17.):
    folder = tmp_path / 'SYNTHETIC_SOURCE'
    folder.mkdir()
    angle = np.deg2rad(tilt)
    # Sagittal K-axis points towards negative LPS x, with an oblique in-plane roll.
    base = np.array([[0., 0., -1.], [1., 0., 0.], [0., -1., 0.]])
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0.], [np.sin(angle), np.cos(angle), 0.], [0., 0., 1.]])
    direction = rotation @ base
    origin = (-30., -20., 10.) if side == 'R' else (30., -20., 10.)
    mri = folder / 'image.nii.gz'
    native = write_image(mri, np.arange(5*8*10, dtype=np.int16).reshape(5, 8, 10), origin, direction, (.5, .5, 2.))
    binary = np.zeros((20, 8, 10), dtype=np.uint8)
    binary[0:6, 2:6, 2:8] = 1
    binary[12:20, 1:7, 1:9] = 1
    binary[7, 0, 0] = 1  # A tiny original fragment between acquired planes: never filter it.
    pred = tmp_path / 'SYNTHETIC_ORIGINAL.nii.gz'
    source = write_image(pred, binary, origin, direction, (.5, .5, .5))
    a = affine_lps(source)
    low, high = np.argwhere(binary[:10] > 0), np.argwhere(binary[10:] > 0)
    high[:, 0] += 10
    lx = float((a @ np.r_[low.mean(0)[::-1], 1.])[0])
    hx = float((a @ np.r_[high.mean(0)[::-1], 1.])[0])
    mlow = lx > hx if side == 'R' else lx < hx
    context = {'case_key': 'SYNTHETIC_CASE', 'source_series_key': 'SYNTHETIC_SERIES', 'series_instance_uid': 'SYNTHETIC_UID',
               'image_sha256': sha256(mri), 'knee_side': side,
               'source_prediction': {'sha256': sha256(pred), 'pipeline_version': 'SYNTHETIC_RELEASE', 'model_version': 'SYNTHETIC_MODEL', 'identity': 'SYNTHETIC_SOURCE_MASK'},
               'existing_split': {'split': True, 'split_cut_plane': 10, 'medial_is_low_index': bool(mlow), 'split_method': 'april', 'x_low_index_mm': lx, 'x_high_index_mm': hx},
               'source_grid_dimensions_xyz': list(source.GetSize())}
    meta = {key: context[key] for key in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256', 'knee_side')}
    meta.update(dimensions_xyz=list(native.GetSize()), spacing_xyz_mm=list(native.GetSpacing()), origin_lps_mm=list(native.GetOrigin()), direction_lps_columns=direction.tolist())
    (folder / 'case.json').write_text(json.dumps(meta))
    return mri, pred, context, binary, native, source


def run(tmp_path, side='R'):
    mri, pred, context, binary, native, source = fixture(tmp_path, side)
    output = tmp_path / 'reader/starting_mask.nii.gz'
    public = tmp_path / 'reader/starting_mask.json'
    private = tmp_path / 'private/report.json'
    report = prepare(mri, pred, context, output, public, private)
    return report, output, public, (mri, pred, context, binary, native, source)


@pytest.mark.parametrize('side', ['L', 'R'])
def test_oblique_categorical_resampling_matches_physical_known_mapping_and_side(tmp_path, side):
    mri, pred, context, binary, native, source = fixture(tmp_path, side)
    originals = {path: path.read_bytes() for path in (mri, pred, mri.parent / 'case.json')}
    output = tmp_path / 'reader/starting_mask.nii.gz'
    report = prepare(mri, pred, context, output, tmp_path / 'reader/starting_mask.json', tmp_path / 'private/report.json')
    prepared = sitk.ReadImage(str(output))
    array = sitk.GetArrayFromImage(prepared)
    labels, assignment = label_existing_binary(binary, affine_lps(source), side, context['existing_split'])
    expected, _ = physical_nearest(labels, affine_lps(source), affine_lps(native), native.GetSize())
    assert np.array_equal(array, expected)
    assert prepared.GetSize() == native.GetSize()
    assert np.allclose(prepared.GetSpacing(), native.GetSpacing(), atol=1e-6)
    assert np.allclose(prepared.GetOrigin(), native.GetOrigin(), atol=1e-6)
    assert np.allclose(prepared.GetDirection(), native.GetDirection(), atol=1e-6)
    assert np.array_equal(labels > 0, binary > 0)
    assert report['source_label_counts']['1'] + report['source_label_counts']['2'] == int(binary.sum())
    assert not report['prepared_label_counts']['1'] == 0 and not report['prepared_label_counts']['2'] == 0
    assert all(path.read_bytes() == payload for path, payload in originals.items())
    assert report['saved_mask_header']['spatial_units'] == 'mm'
    assert report['sidecar']['status'] == 'unreviewed_automated_prediction'


def test_between_plane_fragment_retained_in_source_and_change_reported_not_filtered(tmp_path):
    report, output, public, values = run(tmp_path)
    binary = values[3]
    assert binary[7, 0, 0] == 1
    assert sum(report['source_label_counts'][str(k)] for k in (1, 2)) == int(binary.sum())
    assert report['sidecar']['transformation']['no_filtering_smoothing_filling_or_fragment_removal']
    assert report['categorical_round_trip_change']['1']['source_voxels_not_recovered'] > 0


def test_no_existing_split_is_unresolved_never_blank(tmp_path):
    mri, pred, context, *_ = fixture(tmp_path)
    context['existing_split'] = {'split': False, 'split_method': 'whole', 'split_cut_plane': None}
    with pytest.raises(StartingMaskError, match='no_existing_anatomical_split'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')
    assert not (tmp_path / 'reader/mask.nii.gz').exists()


def test_recorded_compartment_swap_rejected(tmp_path):
    mri, pred, context, *_ = fixture(tmp_path)
    context['existing_split']['medial_is_low_index'] = not context['existing_split']['medial_is_low_index']
    with pytest.raises(StartingMaskError, match='medial_assignment'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')


def test_shifted_source_rejected_instead_of_header_repair(tmp_path):
    mri, pred, context, binary, native, source = fixture(tmp_path)
    changed = sitk.ReadImage(str(pred))
    changed.SetOrigin(tuple(np.asarray(changed.GetOrigin()) + [2., 0., 0.]))
    sitk.WriteImage(changed, str(pred), True)
    context['source_prediction']['sha256'] = sha256(pred)
    with pytest.raises(StartingMaskError, match='frame_not_native'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')


def test_wrong_bound_mri_identity_and_mask_checksum_rejected(tmp_path):
    mri, pred, context, *_ = fixture(tmp_path)
    context['case_key'] = 'DIFFERENT_SYNTHETIC_CASE'
    with pytest.raises(StartingMaskError, match='context_identity_mismatch'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')
    context['case_key'] = 'SYNTHETIC_CASE'
    context['source_prediction']['sha256'] = '0' * 64
    with pytest.raises(StartingMaskError, match='prediction_checksum'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')


def test_all_integer_values_preserved_or_rejected_not_thresholded(tmp_path):
    mri, pred, context, binary, native, source = fixture(tmp_path)
    binary[4, 3, 3] = 2
    write_image(pred, binary, source.GetOrigin(), np.asarray(source.GetDirection()).reshape(3, 3), source.GetSpacing())
    context['source_prediction']['sha256'] = sha256(pred)
    with pytest.raises(StartingMaskError, match='not_binary'):
        prepare(mri, pred, context, tmp_path / 'reader/mask.nii.gz', tmp_path / 'reader/mask.json', tmp_path / 'private/report.json')


def test_independent_voxel_mapping_rejects_array_flip(tmp_path):
    _, _, context, binary, native, source = fixture(tmp_path)
    labels, _ = label_existing_binary(binary, affine_lps(source), 'R', context['existing_split'])
    expected, _ = physical_nearest(labels, affine_lps(source), affine_lps(native), native.GetSize())
    with pytest.raises(StartingMaskError, match='mapping_mismatch'):
        physical_nearest(labels, affine_lps(source), affine_lps(native), native.GetSize(), expected[::-1])


def test_half_voxel_tie_allows_only_equally_nearest_existing_category():
    source = np.array([[[1, 2, 0]]], dtype=np.uint8)
    a, b = np.eye(4), np.eye(4)
    b[0, 3] = .5
    expected, evidence = physical_nearest(source, a, b, (1, 1, 1), np.array([[[1]]], dtype=np.uint8))
    assert evidence['equally_nearest_alternative_labels_used'] == 1
    with pytest.raises(StartingMaskError, match='tie_not_physically_nearest'):
        physical_nearest(source, a, b, (1, 1, 1), np.array([[[0]]], dtype=np.uint8))


def test_existing_outputs_not_overwritten(tmp_path):
    report, output, public, values = run(tmp_path)
    mri, pred, context, *_ = values
    before = output.read_bytes()
    with pytest.raises(StartingMaskError, match='output_already_exists'):
        prepare(mri, pred, context, output, public, tmp_path / 'private/another.json')
    assert output.read_bytes() == before


def test_nonfinite_physical_mapping_rejected_before_indexing():
    source = np.array([[[1, 2, 0]]], dtype=np.uint8)
    invalid = np.eye(4)
    invalid[0, 3] = np.inf
    with pytest.raises(StartingMaskError, match='physical_mapping_nonfinite'):
        physical_nearest(source, np.eye(4), invalid, (1, 1, 1))


def test_nonfinite_continuous_coordinates_rejected_explicitly(monkeypatch):
    import prepare_starting_mask as module
    original = np.einsum
    def poisoned(specification, left, right, **kwargs):
        result = original(specification, left, right, **kwargs)
        if left.shape == (3, 4):
            result[0, 0] = np.nan
        return result
    monkeypatch.setattr(module.np, 'einsum', poisoned)
    with pytest.raises(StartingMaskError, match='coordinates_nonfinite'):
        physical_nearest(np.array([[[1]]], dtype=np.uint8), np.eye(4), np.eye(4), (1, 1, 1))
