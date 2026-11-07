"""The maintained checker accepts only explicitly bound additive resolutions."""
import copy
import json

import pytest

from test_correction_inputs import package, digest
from correction_inputs import canonical, validate_correction_package
from native_mri_package import VerificationError


@pytest.fixture
def resolved_package(package):
    root, cases, catalog, layouts = package
    case = cases[0];key = case['case_key'];relative = catalog[key]['relative_folder']
    job_path = root / 'correction_job.json';job = json.loads(job_path.read_text())
    start = copy.deepcopy(job['cases'][key]['starting_mask'])
    start['source'] = 'SYNTHETIC documented case-specific derivation';start['version'] = 'SYNTHETIC-RESOLUTION-1'
    job['cases'][key] = {'annotation_mode': 'correction', 'availability': 'unresolved',
                         'starting_mask': None, 'reason': 'SYNTHETIC original prediction has no compartment split'}
    job_path.write_text(json.dumps(job, indent=2))
    entry = {'source_identity': canonical(case), 'source_series_key': case['source_series_key'],
             'series_instance_uid': case['series_instance_uid'], 'source_image_sha256': case['image_sha256'],
             'original_rule_identity': canonical(job['cases'][key]), 'starting_mask': start,
             'provenance': {'path': relative + '/starting_mask.json', 'sha256': digest(root / relative / 'starting_mask.json')}}
    registry = {'schema_version': 'meniscus_correction_resolutions/1', 'base_job_identity': canonical(job),
                'dataset_identity': job['dataset_identity'], 'resolutions': {key: entry}}
    (root / 'correction_resolutions.json').write_text(json.dumps(registry))
    return package, job, registry


def test_complete_additive_package_preserves_original_job_and_records_registry(resolved_package):
    package, job, _ = resolved_package
    root = package[0];before = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()}
    report, expected = validate_correction_package(*package)
    assert report['verified_masks'] == 2 and report['resolved_cases'] == 1
    assert report['correction_package_complete'] and not report['unresolved_cases']
    assert report['base_job_identity'] == canonical(job)
    assert 'correction_resolutions.json' in expected and len(expected) == 6
    assert before == {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('kind', ['base_hash', 'image_hash', 'rule_hash', 'case_key', 'mask_hash', 'sidecar_hash', 'path', 'ready_override'])
def test_invalid_additive_permissions_fail_maintained_route(resolved_package, kind):
    package, job, registry = resolved_package
    root, cases, _, _ = package;key = cases[0]['case_key'];entry = registry['resolutions'][key]
    if kind == 'base_hash':registry['base_job_identity'] = '0' * 64
    elif kind == 'image_hash':entry['source_image_sha256'] = '0' * 64
    elif kind == 'rule_hash':entry['original_rule_identity'] = '0' * 64
    elif kind == 'case_key':registry['resolutions']['SYNTHETIC_UNKNOWN'] = registry['resolutions'].pop(key)
    elif kind == 'mask_hash':entry['starting_mask']['sha256'] = '0' * 64
    elif kind == 'sidecar_hash':entry['provenance']['sha256'] = '0' * 64
    elif kind == 'path':entry['starting_mask']['path'] = '../outside.nii.gz'
    else:registry['resolutions'][cases[1]['case_key']] = copy.deepcopy(entry)
    (root / 'correction_resolutions.json').write_text(json.dumps(registry))
    with pytest.raises(VerificationError):validate_correction_package(*package)


def test_ready_sidecar_without_explicit_resolution_stays_blocked(resolved_package):
    package, _, _ = resolved_package
    (package[0] / 'correction_resolutions.json').unlink()
    with pytest.raises(VerificationError, match='ready_starting_mask_job_invalid'):
        validate_correction_package(*package)
