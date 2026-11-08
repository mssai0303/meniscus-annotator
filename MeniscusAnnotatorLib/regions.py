"""Optional native-grid regional draft annotation, independent of the Slicer UI.

Whole menisci remain primary labels 1/2. Horn/body definitions are not inferred
from voxel or slice coordinates. Every parent voxel is explicitly assigned to
one of its three named regions or its compartment's unassigned value.
"""
from __future__ import annotations

import copy
import datetime as dt

import numpy as np

# Importing this helper from core is safe: definitions are looked up only at call time.
from .core import ValidationError, need

REGIONS = (
    {'value': 1, 'id': 'medial_anterior', 'name': 'Medial anterior horn', 'parent': 'medial'},
    {'value': 2, 'id': 'medial_body', 'name': 'Medial body', 'parent': 'medial'},
    {'value': 3, 'id': 'medial_posterior', 'name': 'Medial posterior horn', 'parent': 'medial'},
    {'value': 4, 'id': 'lateral_anterior', 'name': 'Lateral anterior horn', 'parent': 'lateral'},
    {'value': 5, 'id': 'lateral_body', 'name': 'Lateral body', 'parent': 'lateral'},
    {'value': 6, 'id': 'lateral_posterior', 'name': 'Lateral posterior horn', 'parent': 'lateral'},
)
REGION_IDS = tuple(region['id'] for region in REGIONS)
REGION_BY_ID = {region['id']: region for region in REGIONS}
REGION_LABEL_MAPPING = {'0': 'outside whole menisci; not accepted background',
                        **{str(region['value']): region['name'].lower() for region in REGIONS},
                        '7': 'medial unassigned', '8': 'lateral unassigned'}
UNASSIGNED = {1: 7, 2: 8}
PARENT_VALUES = {'medial': 1, 'lateral': 2}
VALUES_BY_PARENT = {'medial': (1, 2, 3, 7), 'lateral': (4, 5, 6, 8)}
REGIONAL_PROTOCOL = {'version': 'meniscus-regions-pending-1',
                     'status': 'pending_expert_protocol',
                     'scope': 'Anterior horn/body/posterior horn boundaries require an agreed expert anatomical protocol. No regional research approval is enabled.'}
EXTENSION_SCHEMA = 'meniscus_regional_extension/1'
STATE_SCHEMA = 'meniscus_regions/1'
REGIONAL_FILES = frozenset(('regions.nii.gz', 'regional_uncertainty.nii.gz', 'regional_validity.nii.gz', 'regions.json', 'regional_review.csv'))
REVIEW_FIELDS = ['slice_index', 'displayed_slice', 'medial_status', 'lateral_status', 'attention_flag', 'note']
BINDING_KEYS = ('dataset_identity', 'source_identity', 'source_image_sha256', 'case_key', 'job_identity', 'annotator', 'app_version')


def _whole(whole):
    need(isinstance(whole, np.ndarray) and whole.ndim == 3 and np.issubdtype(whole.dtype, np.integer)
         and np.isin(whole, [0, 1, 2]).all(), 'Regional annotation requires the complete native integer whole-meniscus label image (0, 1, 2).')


def _arrays(whole, regions, regional_uncertainty):
    _whole(whole)
    need(isinstance(regions, np.ndarray) and regions.shape == whole.shape
         and np.issubdtype(regions.dtype, np.integer) and np.isin(regions, range(9)).all(),
         'Regional labels must be full-grid integers 0 through 8 with the fixed regional mapping.')
    need(isinstance(regional_uncertainty, np.ndarray) and regional_uncertainty.shape == whole.shape
         and np.issubdtype(regional_uncertainty.dtype, np.integer) and np.isin(regional_uncertainty, [0, 1]).all(),
         'Regional uncertainty must be a separate full-grid binary integer image.')


def initialize(whole):
    """No horn/body inference: every whole voxel starts explicitly unassigned."""
    _whole(whole)
    regions = np.zeros(whole.shape, dtype=np.uint8)
    regions[whole == 1] = 7
    regions[whole == 2] = 8
    return regions


def default_state(n_slices, primary_state):
    need(type(n_slices) is int and n_slices > 0, 'Regional review requires every acquired slice.')
    state = {'schema_version': STATE_SCHEMA, 'label_mapping': copy.deepcopy(REGION_LABEL_MAPPING),
             'array_convention': 'files IJK; application arrays KJI; displayed slice n = stored k + 1',
             'protocol': copy.deepcopy(REGIONAL_PROTOCOL), 'status': 'draft',
             'research_approved': False, 'approval': None,
             'assessments': {key: {'status': 'unassessed', 'note': ''} for key in REGION_IDS},
             'review': [{'slice_index': k, 'medial_reviewed': False, 'lateral_reviewed': False, 'flag': False, 'note': ''} for k in range(n_slices)],
             'notes': '', 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'saved_utc': None,
             'uncertainty_policy': 'Separate regional binary overlay within the whole-meniscus union; may overlap any assigned or unassigned region. Never a training class or confirmed background.',
             'validity_policy': 'All regional validity is zero while expert protocol is pending. Unassigned, uncertain, unreviewed and practice voxels are never accepted regional targets.',
             'initialization': {'method': 'unassigned_from_whole_menisci', 'automatic_anatomical_partition': False}}
    for key in BINDING_KEYS:
        state[key] = copy.deepcopy(primary_state.get(key))
    state['practice_context'] = copy.deepcopy(primary_state.get('practice_context'))
    state['reader_assignment'] = copy.deepcopy(primary_state.get('reader_assignment'))
    state['runtime'] = copy.deepcopy(primary_state.get('runtime'))
    return state


def validate_state(state, n_slices, primary_state=None):
    need(isinstance(state, dict) and state.get('schema_version') == STATE_SCHEMA, 'Regional metadata schema is unsupported.')
    need(state.get('label_mapping') == REGION_LABEL_MAPPING, 'Regional label mapping changed or is incomplete.')
    need(state.get('protocol') == REGIONAL_PROTOCOL and state.get('research_approved') is False
         and state.get('approval') is None and state.get('status') == 'draft',
         'Regional annotation must remain a draft with pending expert protocol; research approval is not enabled.')
    need(isinstance(state.get('notes'), str), 'Regional notes must be text.')
    assessments = state.get('assessments')
    need(isinstance(assessments, dict) and set(assessments) == set(REGION_IDS), 'Every named region requires a separate assessment record.')
    for item in assessments.values():
        need(isinstance(item, dict) and set(item) == {'status', 'note'}
             and item.get('status') in ('unassessed', 'present', 'absent', 'uncertain') and isinstance(item.get('note'), str),
             'Regional assessment must record unassessed, present, absent or uncertain and a text note.')
    review = state.get('review')
    need(isinstance(review, list) and len(review) == n_slices, 'Regional review must contain every acquired slice.')
    for k, row in enumerate(review):
        need(isinstance(row, dict) and set(row) == {'slice_index', 'medial_reviewed', 'lateral_reviewed', 'flag', 'note'}
             and type(row.get('slice_index')) is int and row['slice_index'] == k
             and all(type(row.get(key)) is bool for key in ('medial_reviewed', 'lateral_reviewed', 'flag'))
             and isinstance(row.get('note'), str), 'Regional review records are incomplete or incorrectly indexed.')
    if primary_state is not None:
        for key in (*BINDING_KEYS, 'practice_context', 'reader_assignment'):
            need(state.get(key) == primary_state.get(key), 'Regional source, job or reader attribution differs from the unchanged whole-meniscus annotation: ' + key)


def validate(whole, regions, regional_uncertainty, state, primary_state=None):
    """Reject mismatched parents, overlap/missing partition, geometry and attribution."""
    _arrays(whole, regions, regional_uncertainty)
    validate_state(state, whole.shape[0], primary_state)
    need(np.all(regions[whole == 0] == 0), 'Regional labels extend outside both whole menisci.')
    for parent, whole_value in PARENT_VALUES.items():
        need(np.isin(regions[whole == whole_value], VALUES_BY_PARENT[parent]).all(),
             parent.capitalize() + ' whole meniscus must be exhaustively partitioned into its three regions and explicit unassigned label; opposite-compartment labels are invalid.')
    for region in REGIONS:
        need(state['assessments'][region['id']]['status'] != 'absent' or not np.any(regions == region['value']),
             region['name'] + ' is declared absent but contains assigned voxels. Remove its assignments or update the assessment.')
    need(not np.any((regional_uncertainty != 0) & (whole == 0)), 'Regional uncertainty extends outside the whole-meniscus union.')


def invalidate_review(state, indices, compartments=('medial', 'lateral')):
    result = copy.deepcopy(state)
    need(all(parent in PARENT_VALUES for parent in compartments), 'Unknown regional review compartment.')
    for index in indices:
        need(isinstance(index, (int, np.integer)) and not isinstance(index, (bool, np.bool_)) and 0 <= index < len(result['review']), 'Regional review change is outside the acquired volume.')
        for parent in compartments:
            result['review'][index][parent + '_reviewed'] = False
    result.update(status='draft', research_approved=False, approval=None)
    return result


def reconcile(whole, regions, regional_uncertainty, state, previous_whole=None):
    """Contain regions inside current parents, preserving valid native Undo restores.

    previous_whole affects review invalidation only. A newly added whole voxel
    whose matching region is already restored by native Undo retains that region.
    A voxel without a valid region becomes explicit medial/lateral unassigned.
    """
    _arrays(whole, regions, regional_uncertainty)
    validate_state(state, whole.shape[0])
    result = regions.astype(np.uint8, copy=True)
    uncertain = regional_uncertainty.astype(np.uint8, copy=True)
    updated = copy.deepcopy(state)
    result[whole == 0] = 0
    uncertain[whole == 0] = 0
    for parent, value in PARENT_VALUES.items():
        wrong = (whole == value) & ~np.isin(result, VALUES_BY_PARENT[parent])
        result[wrong] = UNASSIGNED[value]
        changed = ((regions != result) & (np.isin(regions, VALUES_BY_PARENT[parent]) | (whole == value)))
        if previous_whole is not None:
            _whole(previous_whole)
            need(previous_whole.shape == whole.shape, 'Previous whole-meniscus grid differs from regional annotation.')
            changed |= ((previous_whole == value) != (whole == value))
        changed |= ((regional_uncertainty != uncertain) & (np.isin(regions, VALUES_BY_PARENT[parent]) | (whole == value)))
        indices = [int(k) for k in np.flatnonzero(np.any(changed, axis=(1, 2)))]
        updated = invalidate_review(updated, indices, (parent,))
    validate(whole, result, uncertain, updated)
    return result, uncertain, updated


def validity(whole, whole_uncertainty, regions, regional_uncertainty, state, primary_state=None):
    validate(whole, regions, regional_uncertainty, state, primary_state)
    need(isinstance(whole_uncertainty, np.ndarray) and whole_uncertainty.shape == whole.shape
         and np.isin(whole_uncertainty, [0, 1]).all(), 'Whole-meniscus uncertainty grid is invalid.')
    # Deliberately unconditional in this schema. A future released expert
    # protocol requires a separately versioned, tested contract and reader.
    return np.zeros(whole.shape, dtype=np.uint8)


def completeness(whole, regions, regional_uncertainty, state):
    validate(whole, regions, regional_uncertainty, state)
    total = int(np.count_nonzero(whole))
    assigned = int(np.count_nonzero((regions >= 1) & (regions <= 6)))
    unassigned = int(np.count_nonzero((regions == 7) | (regions == 8)))
    result = {'whole_voxels': total, 'assigned_voxels': assigned, 'unassigned_voxels': unassigned,
              'regional_uncertain_voxels': int(np.count_nonzero(regional_uncertainty)),
              'flagged_slices': sum(row['flag'] for row in state['review']),
              'medial_reviewed_slices': sum(row['medial_reviewed'] for row in state['review']),
              'lateral_reviewed_slices': sum(row['lateral_reviewed'] for row in state['review']),
              'acquired_slices': len(state['review']),
              'assigned_partition_complete': unassigned == 0,
              'regional_research_approved': False, 'protocol_status': 'pending_expert_protocol',
              'by_region': {r['id']: {'voxels': int(np.count_nonzero(regions == r['value'])),
                                    'assessment': copy.deepcopy(state['assessments'][r['id']])} for r in REGIONS}}
    return result


def completion_errors(whole, whole_uncertainty, regions, regional_uncertainty, state, primary_state=None):
    try:
        validity(whole, whole_uncertainty, regions, regional_uncertainty, state, primary_state)
    except ValidationError as exc:
        return [str(exc)]
    errors = ['Regional research approval is unavailable: horn/body boundaries await an agreed expert anatomical protocol.']
    if np.any((regions == 7) | (regions == 8)):
        errors.append('Assign or explicitly resolve all medial and lateral unassigned voxels.')
    if regional_uncertainty.any() or whole_uncertainty.any() or any(row['flag'] for row in state['review']):
        errors.append('Resolve whole/regional uncertainty and regional attention flags.')
    if not all(row['medial_reviewed'] and row['lateral_reviewed'] for row in state['review']):
        errors.append('Explicitly review both compartments on every acquired slice, including empty slices.')
    for r in REGIONS:
        assessment = state['assessments'][r['id']]['status']
        present = bool(np.any(regions == r['value']))
        if assessment in ('unassessed', 'uncertain'):
            errors.append(r['name'] + ' requires an explicit present/absent assessment.')
        elif (assessment == 'absent' and present) or (assessment == 'present' and not present):
            errors.append(r['name'] + ' assessment conflicts with its current assigned voxels.')
    if primary_state and (primary_state.get('practice_context') is not None or primary_state.get('status') == 'practice_approved'):
        errors.append('Software/practice annotations are not accepted regional research targets.')
    return errors


def review_rows(state):
    """Canonical CSV rows; compare on reload as well as write."""
    return [{'slice_index': str(row['slice_index']), 'displayed_slice': str(row['slice_index'] + 1),
             'medial_status': 'reviewed' if row['medial_reviewed'] else 'not_reviewed',
             'lateral_status': 'reviewed' if row['lateral_reviewed'] else 'not_reviewed',
             'attention_flag': str(int(row['flag'])), 'note': row['note']} for row in state['review']]
