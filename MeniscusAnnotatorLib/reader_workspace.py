"""Pure work-location planning for immutable reader assignments.

No directories, settings, jobs or checkpoints are created or changed here.
Callers must validate the dataset/job before using the returned location.
"""
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re


def reader_workspace(dataset_version, job=None, reader=None):
    """Return a safe default folder/key without identifying the runtime operator.

    Explicit ordinary reader assignments get separate work locations bound to
    the entire immutable base job. A BoundCorrectionJob's ``source_job`` is used
    instead of its effective rules so additive case resolutions do not move
    existing work. Ordinary jobs without an annotator require an explicitly
    chosen local reader, whose assignment gets its own folder and settings key.
    Software-practice jobs retain their original version-only location and key.

    ``legacy_settings_key`` is a recovery hint, NOT an automatic fallback for a
    reader assignment. A coordinator may explicitly reconnect an existing work
    folder after checking its original job/reader; core checkpoint validation
    still applies. Never move or relabel old work merely because this key exists.
    """
    reserved = {'CON', 'PRN', 'AUX', 'NUL',
                *('COM' + str(i) for i in range(1, 10)),
                *('LPT' + str(i) for i in range(1, 10))}
    if (not isinstance(dataset_version, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', dataset_version)
            or dataset_version.endswith('.')
            or dataset_version.upper().split('.')[0] in reserved):
        raise ValueError('Dataset version must be a safe portable folder identifier.')
    source = getattr(job, 'source_job', job)
    if source is not None and not isinstance(source, Mapping):
        raise ValueError('Reader workspace requires a validated job dictionary.')
    source = source or {}
    if 'annotator' in source and (not isinstance(source['annotator'], str)
                                  or not source['annotator'].strip()):
        raise ValueError('An explicit reader assignment must have a nonempty name.')
    encoded = json.dumps(dict(source), sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode('utf-8')
    identity = hashlib.sha256(encoded).hexdigest() if source else None
    named = 'annotator' in source and source.get('practice_context') is None
    local = not named and source.get('practice_context') is None
    assignment_identity = None
    if local:
        if not isinstance(reader, str) or not reader.strip():
            raise ValueError('Enter a nonempty reader name or study ID before choosing a work folder.')
        reader = reader.strip()
        assignment = {'schema_version': 'meniscus_reader_assignment/1',
                      'base_job_identity': identity, 'reader': reader}
        assignment_identity = hashlib.sha256(json.dumps(
            assignment, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')).hexdigest()
    elif named:
        reader = source['annotator']
    else:
        reader = source['practice_context'].get('actor')
    legacy_key = 'Meniscus/work/' + dataset_version
    # Names never enter filenames, so Unicode/slashes/reserved words in a
    # legitimate reader name cannot alter filesystem layout or Windows paths.
    suffix = 'assignment-' + identity[:24] if named else None
    settings_key = legacy_key + '/assignment-' + identity if named else legacy_key
    if local:
        suffix = 'reader-' + assignment_identity[:24]
        settings_key = legacy_key + '/reader-' + assignment_identity
    return {
        'uses_named_assignment': named,
        'uses_local_reader_assignment': local,
        'base_job_identity': identity,
        'reader': reader,
        'reader_assignment_identity': assignment_identity,
        'settings_key': settings_key,
        'legacy_settings_key': legacy_key,
        'relative_folder': Path(dataset_version) / suffix if suffix else Path(dataset_version),
    }
