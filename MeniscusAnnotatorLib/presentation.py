"""Physical-geometry presentation and advisory checks for the OAI importer.

These functions do not change arrays, labels, transforms or annotation rules.
They assume the original orthogonal acquired grid has passed input validation.
"""
import numpy as np


def acquired_display_frame(affine_ras):
    """Right-handed display frame, superior up and anterior left when supported.

    Display normal may oppose the stored K direction. Its planes are identical;
    displayed slice n still means stored k=n-1, not the renderer's offset order.
    """
    affine = np.asarray(affine_ras, dtype=float)
    if affine.shape != (4, 4) or not np.isfinite(affine).all():
        raise ValueError('A finite original image affine is required.')
    normal = affine[:3, 2] / np.linalg.norm(affine[:3, 2])
    up = affine[:3, 1] / np.linalg.norm(affine[:3, 1])
    if up[2] < 0:
        up = -up
    horizontal = np.cross(up, normal)
    horizontal /= np.linalg.norm(horizontal)
    # RAS +Y is anterior. Screen-left is -horizontal. Reverse BOTH horizontal
    # and normal to retain a proper right-handed slice frame (never flip data).
    if horizontal[1] > 0:
        horizontal = -horizontal
        normal = -normal
    frame = np.column_stack((horizontal, up, normal))
    if not np.allclose(frame.T @ frame, np.eye(3), atol=1e-6) or np.linalg.det(frame) < .999:
        raise ValueError('The acquired image frame is unsupported. Reconnect the verified original scan.')
    return frame


def slice_direction(affine_ras, knee_side, minimum_lr_component=.75):
    """Describe increasing stored K from physical RAS geometry and explicit side."""
    if knee_side not in ('L', 'R'):
        raise ValueError('Verified left/right knee metadata is required.')
    step = np.asarray(affine_ras, dtype=float)[:3, 2]
    direction = step / np.linalg.norm(step)
    lr = float(direction[0])
    if abs(lr) < minimum_lr_component:
        toward, label = 'ambiguous', 'Next: oblique direction'
        explanation = 'Slice advance has a substantial mixed direction. Use the physical orientation letters; medial/lateral advance is not asserted.'
    else:
        toward = 'medial' if (lr > 0) == (knee_side == 'L') else 'lateral'
        label = 'Next: toward ' + toward
        explanation = 'Increasing the acquired slice number moves predominantly toward ' + toward + '. This follows physical image geometry and the recorded knee side.'
    return {'toward': toward, 'label': label, 'explanation': explanation,
            'physical_step_ras_mm': step.tolist(), 'lr_component': lr}


def label_plausibility(labels_kji, affine_ras, knee_side, tolerance_mm=2., minimum_voxels=20):
    """Advisory relative medial/lateral position check; never anatomical proof.

    Use the median physical left/right position, so small outlying fragments
    have limited influence. Sparse/missing labels or small separation produce
    an indeterminate result rather than certainty. No label is modified.
    """
    if knee_side not in ('L', 'R'):
        raise ValueError('Verified knee side is required.')
    labels = np.asarray(labels_kji)
    affine = np.asarray(affine_ras, dtype=float)
    if labels.ndim != 3 or affine.shape != (4, 4):
        raise ValueError('Full native labels and their original affine are required.')
    positions, counts = {}, {}
    for value in (1, 2):
        coordinates = np.argwhere(labels == value)
        counts[value] = len(coordinates)
        if len(coordinates) < minimum_voxels:
            return {'status': 'indeterminate', 'advisory_only': True,
                    'message': 'Medial/lateral position check is inconclusive: a label is missing or very small. Inspect both labels.',
                    'counts': counts}
        ijk = coordinates[:, ::-1]
        positions[value] = float(np.median(ijk @ affine[0, :3] + affine[0, 3]))
    separation = (positions[1] - positions[2]) * (1 if knee_side == 'L' else -1)
    # Include sampling along LR in the tolerance; this is not an anatomical
    # minimum size or a reason to add/remove tissue.
    tolerance = max(float(tolerance_mm), float(np.max(np.abs(affine[0, :3]))))
    status = 'check' if separation < -tolerance else ('indeterminate' if separation <= tolerance else 'no_concern')
    message = {'check': 'Check medial/lateral labels on this case. Their relative physical positions are unexpected for the recorded knee side. Inspect the MRI; labels have not been changed.',
               'indeterminate': 'Medial/lateral positions are close or overlap. Inspect both labels; this check is inconclusive.',
               'no_concern': 'No simple positional disagreement detected. This is not anatomical validation.'}[status]
    return {'status': status, 'advisory_only': True, 'message': message,
            'counts': counts, 'median_ras_x_mm': positions,
            'expected_signed_separation_mm': float(separation), 'tolerance_mm': tolerance}
