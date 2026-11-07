"""Canonical reader-folder layouts; identity comes from unchanged case metadata.

No source key, case identity, dataset identity or image content is changed by a
layout choice. Legacy packages may retain only their known empty annotations dir.
"""
from pathlib import Path, PurePosixPath
import re

FLAT = 'flat'
LEGACY = 'legacy'
CASE_FILES = frozenset(('image.nii.gz', 'case.json', 'slice_review.csv'))
STARTING_MASK_FILES = frozenset(('starting_mask.nii.gz', 'starting_mask.json'))


def _token(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value) or value.endswith('.'):
        raise ValueError('unsafe_' + name)
    return value


def canonical_relative_folder(metadata, layout=FLAT):
    participant = _token(metadata['participant_id'], 'participant_id')
    raw_month = metadata['visit_month']
    if isinstance(raw_month, bool) or not re.fullmatch(r'[0-9]{1,3}', str(raw_month)):
        raise ValueError('invalid_visit_month')
    month = int(raw_month)
    side = {'L': 'LEFT', 'R': 'RIGHT'}.get(metadata['knee_side'])
    if side is None:
        raise ValueError('invalid_knee_side')
    if layout == FLAT:
        return 'Cases/OAI_%s_M%03d_%s' % (participant, month, side)
    if layout == LEGACY:
        source = _token(metadata['source_series_key'], 'source_series_key')
        return 'Cases/OAI_%s/M%03d/%s/series_%s' % (participant, month, side, source)
    raise ValueError('unsupported_folder_layout')


def verify_relative_folder(relative, metadata):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('unsafe_relative_folder')
    path = PurePosixPath(relative)
    # Exact spelling avoids . components, duplicate separators and platform paths.
    if path.is_absolute() or path.as_posix() != relative or any(p in ('.', '..') for p in path.parts):
        raise ValueError('unsafe_relative_folder')
    for layout in (FLAT, LEGACY):
        if relative == canonical_relative_folder(metadata, layout):
            return layout
    raise ValueError('case_folder_identity_mismatch')


def checked_case_contents(folder, layout, correction=False, allow_unresolved=False):
    if layout not in (FLAT, LEGACY):
        raise ValueError('unsupported_folder_layout')
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('case_folder_missing_or_symlink')
    contents = {path.name for path in folder.iterdir()}
    allowed = set(CASE_FILES)
    if correction:
        # A documented unresolved case has provenance only, never an empty mask.
        if 'starting_mask.nii.gz' in contents:
            allowed.update(STARTING_MASK_FILES)
        elif allow_unresolved:
            allowed.add('starting_mask.json')
        else:
            raise ValueError('missing_prepared_starting_mask')
    annotation_folder = folder / 'annotations'
    if annotation_folder.exists() or annotation_folder.is_symlink():
        if layout != LEGACY:
            raise ValueError('unexpected_annotations_directory_in_flat_layout')
        if annotation_folder.is_symlink() or not annotation_folder.is_dir() or any(annotation_folder.iterdir()):
            raise ValueError('annotations_not_empty_or_unsafe')
        allowed.add('annotations')
    if contents != allowed:
        raise ValueError('unexpected_or_missing_case_contents')
    if any((folder / name).is_symlink() or not (folder / name).is_file() for name in allowed if name != 'annotations'):
        raise ValueError('case_file_missing_or_symlink')
    return contents
