import numpy as np
import pytest

from MeniscusAnnotatorLib.presentation import acquired_display_frame, slice_direction, label_plausibility


@pytest.mark.parametrize('side', ['L', 'R'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('oblique', [False, True])
def test_view_only_anterior_left_and_exact_acquired_plane(side, reverse, oblique):
    base = np.array([[0., 0., 1.], [-1., 0., 0.], [0., 1., 0.]])
    if oblique:
        a, b = np.deg2rad([24., -13.])
        rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
        base = rz @ ry @ base
    if reverse:
        base = base @ np.diag([-1., 1., -1.])
    affine = np.eye(4)
    affine[:3, :3] = base @ np.diag([.37, .43, 2.8])
    affine[:3, 3] = [34., -18., -6.]
    before = affine.copy()
    frame = acquired_display_frame(affine)
    assert frame[1, 0] < 0  # RAS +Y anterior lies on screen-left.
    assert frame[2, 1] > 0
    assert np.isclose(np.linalg.det(frame), 1)
    assert np.isclose(abs(np.dot(frame[:, 2], base[:, 2])), 1)
    for k in (0, 4, 10):
        centre = affine @ [47.5, 39.5, k, 1]
        for x, y in [(-8., -4.), (6., 3.)]:
            point = np.r_[centre[:3] + frame[:, 0]*x + frame[:, 1]*y, 1]
            assert np.isclose((np.linalg.inv(affine) @ point)[2], k)
    cue = slice_direction(affine, side)
    expected = 'medial' if (affine[0, 2] > 0) == (side == 'L') else 'lateral'
    assert cue['toward'] == expected
    assert np.array_equal(affine, before)


def test_ambiguous_physical_advance_is_not_claimed_medial_or_lateral():
    affine = np.eye(4)
    affine[:3, 2] = [.2, .8, .3]
    assert slice_direction(affine, 'R')['toward'] == 'ambiguous'


@pytest.mark.parametrize('side', ['L', 'R'])
def test_plausibility_advises_but_never_relabels(side):
    labels = np.zeros((12, 16, 24), dtype=np.uint8)
    labels[3:7, 4:8, 15:19] = 1
    labels[3:7, 4:8, 3:7] = 2
    affine = np.diag([1., 1., 2., 1.])
    before = labels.copy()
    result = label_plausibility(labels, affine, side)
    assert result['status'] == ('no_concern' if side == 'L' else 'check')
    assert result['advisory_only']
    assert np.array_equal(labels, before)


def test_missing_tiny_and_close_labels_are_inconclusive():
    labels = np.zeros((5, 5, 8), dtype=np.uint8)
    affine = np.diag([.4, .5, 3., 1.])
    assert label_plausibility(labels, affine, 'L')['status'] == 'indeterminate'
    labels[:, :, 1] = 1
    labels[:, :, 2] = 2
    assert label_plausibility(labels, affine, 'L')['status'] == 'indeterminate'
    labels[0, 0, 2] = 0
    labels[labels == 2] = 0
    labels[0, 0, 7] = 2
    assert label_plausibility(labels, affine, 'L')['status'] == 'indeterminate'
