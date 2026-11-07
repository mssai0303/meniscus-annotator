"""Pure work-location planning for immutable reader assignments.

No directories, settings, jobs or checkpoints are created or changed here.
Callers must validate the dataset/job before using the returned location.
"""
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re


def reader_workspace(dataset_version, job=None):
    """Return a safe default folder/key without identifying the runtime operator.

    Explicit ordinary reader assignments get separate work locations bound to
    the entire immutable base job. A BoundCorrectionJob's ``source_job`` is used
    instead of its effective rules so additive case resolutions do not move
    existing work. Jobs without an explicit annotator and software-practice jobs
    retain their original version-only location and settings key.

    ``legacy_settings_key`` is a recovery hint, NOT an automatic fallback for a
    named assignment. A coordinator may explicitly reconnect an existing work
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
    legacy_key = 'Meniscus/work/' + dataset_version
    # Names never enter filenames, so Unicode/slashes/reserved words in a
    # legitimate reader name cannot alter filesystem layout or Windows paths.
    suffix = 'assignment-' + identity[:24] if named else None
    return {
        'uses_named_assignment': named,
        'base_job_identity': identity,
        'settings_key': legacy_key + '/assignment-' + identity if named else legacy_key,
        'legacy_settings_key': legacy_key,
        'relative_folder': Path(dataset_version) / suffix if named else Path(dataset_version),
    }
