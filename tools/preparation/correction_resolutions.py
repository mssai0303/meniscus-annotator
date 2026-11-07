"""Additive, case-scoped correction permissions; the original job is immutable.

This contract module has no imaging dependency. The application and maintained
preparation checker each verify the resulting native categorical mask as well.
The standalone preparation copy is deployed byte-for-byte from this source.
"""
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = 'meniscus_correction_resolutions/1'
BINDING_SCHEMA = 'meniscus_case_resolution_binding/1'
FILENAME = 'correction_resolutions.json'
ENTRY_FIELDS = {'source_identity', 'source_series_key', 'series_instance_uid',
                'source_image_sha256', 'original_rule_identity', 'starting_mask', 'provenance'}
LABEL_MAPPING = {'0': 'no predicted meniscus', '1': 'medial meniscus', '2': 'lateral meniscus'}
READY_FIELDS = {'schema_version', 'case_key', 'source_series_key', 'series_instance_uid',
                'image_sha256', 'status', 'source_prediction', 'verification',
                'prepared_mask_sha256', 'label_mapping', 'transformation'}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _relative(root, name, need):
    need(isinstance(name, str) and bool(name) and '\\' not in name,
         'Correction resolution contains an unsafe relative path.')
    relative = PurePosixPath(name)
    need(not relative.is_absolute() and relative.as_posix() == name and '..' not in relative.parts,
         'Correction resolution contains an unsafe relative path.')
    path = Path(root).joinpath(*relative.parts)
    need(path.resolve().is_relative_to(Path(root).resolve()), 'Correction resolution path leaves the dataset.')
    current = path
    while current != Path(root):
        need(not current.is_symlink(), 'Correction resolution paths must not contain a symbolic link.')
        current = current.parent
    return path


def resolve_registry(root, base_job, dataset_identity, cases, need, sha256, read_json):
    """Return explicit effective rules/bindings without modifying ``base_job``.

    ``cases`` maps keys to {metadata, relative_folder}. A binding hashes only its
    own entry, not unrelated additions to the registry. All referenced bytes are
    verified even during metadata-only job checks. No old ready rule may change.
    """
    path = Path(root) / FILENAME
    if not path.exists() and not path.is_symlink():
        return {}, {}, None
    need(not path.is_symlink() and path.is_file(), 'Correction resolution registry must be a regular local file.')
    registry = read_json(path)
    need(isinstance(registry, dict) and set(registry) == {'schema_version', 'base_job_identity', 'dataset_identity', 'resolutions'}
         and registry.get('schema_version') == SCHEMA, 'Correction resolution registry schema is invalid.')
    base_identity = canonical(base_job)
    need(registry['base_job_identity'] == base_identity, 'Correction resolution base job identity does not match the unchanged original job.')
    need(registry['dataset_identity'] == dataset_identity, 'Correction resolution dataset identity is mismatched.')
    entries = registry['resolutions']
    need(isinstance(entries, dict) and bool(entries) and set(entries).issubset(cases),
         'Correction resolution registry contains an unknown case or no explicit resolution.')
    effective, bindings = {}, {}
    rules = base_job.get('cases', {})
    for key, entry in entries.items():
        rule = rules.get(key, {})
        need(rule.get('annotation_mode') == 'correction' and rule.get('availability') == 'unresolved'
             and rule.get('starting_mask', 'MISSING') is None and isinstance(rule.get('reason'), str) and rule['reason'].strip(),
             'Correction resolutions may only resolve an originally unresolved correction rule; ready cases cannot be overridden.')
        need(isinstance(entry, dict) and set(entry) == ENTRY_FIELDS, 'Correction resolution entry schema is invalid.')
        case = cases[key]['metadata']
        need(entry['source_identity'] == canonical(case) and entry['source_image_sha256'] == case['image_sha256']
             and entry['source_series_key'] == case['source_series_key'] and entry['series_instance_uid'] == case['series_instance_uid'],
             'Correction resolution exact case/source identity is mismatched.')
        need(entry['original_rule_identity'] == canonical(rule), 'Correction resolution original unresolved rule identity is mismatched.')
        start, provenance = entry['starting_mask'], entry['provenance']
        need(isinstance(start, dict) and set(start) == {'path', 'sha256', 'source', 'version'}
             and all(isinstance(v, str) and v.strip() for v in start.values()), 'Correction resolution starting-mask permission is incomplete.')
        need(isinstance(provenance, dict) and set(provenance) == {'path', 'sha256'}
             and all(isinstance(v, str) and v.strip() for v in provenance.values()), 'Correction resolution provenance binding is incomplete.')
        mask = _relative(root, start['path'], need)
        sidecar = _relative(root, provenance['path'], need)
        relative = cases[key]['relative_folder']
        need(start['path'] == relative + '/starting_mask.nii.gz' and provenance['path'] == relative + '/starting_mask.json',
             'Correction resolution files must belong to the exact case folder.')
        need(mask.is_file() and sha256(mask) == start['sha256'], 'Correction resolution starting-mask checksum is mismatched or unavailable.')
        need(sidecar.is_file() and sha256(sidecar) == provenance['sha256'], 'Correction resolution provenance checksum is mismatched or unavailable.')
        metadata = read_json(sidecar)
        need(isinstance(metadata, dict) and set(metadata) == READY_FIELDS and metadata.get('schema_version') == 'meniscus_starting_mask/1'
             and metadata.get('status') == 'unreviewed_automated_prediction', 'Resolved starting mask must remain an explicit unreviewed prediction.')
        need(all(metadata.get(field) == case[field] for field in ('case_key', 'source_series_key', 'series_instance_uid', 'image_sha256'))
             and metadata.get('prepared_mask_sha256') == start['sha256'] and metadata.get('label_mapping') == LABEL_MAPPING,
             'Correction resolution provenance case, mask or label binding is mismatched.')
        source, transform, verification = metadata.get('source_prediction'), metadata.get('transformation'), metadata.get('verification')
        need(isinstance(source, dict) and all(isinstance(source.get(field), str) and source[field].strip()
             for field in ('sha256', 'pipeline_version', 'model_version')) and re.fullmatch(r'[0-9a-f]{64}', source['sha256']),
             'Correction resolution source prediction provenance is incomplete.')
        need(isinstance(transform, dict) and isinstance(transform.get('method'), str) and transform['method'].strip(),
             'Correction resolution transformation provenance is missing.')
        need(isinstance(verification, dict) and verification.get('status') == 'verified'
             and all(verification.get(field) is True for field in ('native_grid_match', 'independent_target_voxel_mapping_match', 'output_labels_valid')),
             'Correction resolution technical verification is incomplete.')
        effective[key] = {'annotation_mode': 'correction', 'availability': 'ready', 'starting_mask': copy.deepcopy(start)}
        evidence = {'schema_version': SCHEMA, 'base_job_identity': base_identity,
                    'dataset_identity': dataset_identity, 'case_key': key, 'resolution': copy.deepcopy(entry)}
        bindings[key] = {'schema_version': BINDING_SCHEMA, 'base_job_identity': base_identity,
                         'dataset_identity': dataset_identity, 'case_key': key, 'source_identity': entry['source_identity'],
                         'resolution_identity': canonical(evidence), 'resolution': copy.deepcopy(entry)}
    return effective, bindings, copy.deepcopy(registry)
