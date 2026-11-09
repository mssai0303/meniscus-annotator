"""Optional regional extension: synthetic partitions only, never anatomy validation."""
import copy
import csv
import errno
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import nibabel as nib
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeniscusAnnotatorLib import Dataset, WorkStore, ValidationError, export_approved, sha256
from MeniscusAnnotatorLib import core, regions as regional
from tools.make_synthetic import make_synthetic


@pytest.fixture
def setup(tmp_path):
    source = make_synthetic(tmp_path / 'Source 空間')
    dataset = Dataset(source)
    store = WorkStore(tmp_path / 'Local regional work', dataset, reader='Synthetic Regional Reader')
    return source, dataset, store


def writer(path):
    path.write_bytes(b'SYNTHETIC CORE TEST MARKER; actual Slicer storage tested separately')


def labelled(session):
    whole, uncertain = session.blank_arrays()
    whole[3, 10:15, 10:19] = 1
    whole[5, 20:25, 25:34] = 2
    return whole, uncertain


def region_state(session, whole):
    return regional.initialize(whole), np.zeros_like(whole), regional.default_state(whole.shape[0], session.state)


def partition_all(whole):
    result = regional.initialize(whole)
    for parent, values in ((1, (1, 2, 3)), (2, (4, 5, 6))):
        positions = np.argwhere(whole == parent)
        for index, coordinate in enumerate(positions):
            result[tuple(coordinate)] = values[index % 3]
    return result


def finish_primary(session):
    for row in session.state['review']:
        row['reviewed'] = True
    session.state['compartments'] = {'medial': True, 'lateral': True}


def file_hashes(folder):
    return {str(path.relative_to(folder)): sha256(path) for path in folder.rglob('*') if path.is_file()}


def test_initialization_explicit_unassigned_no_horn_inference(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region = regional.initialize(whole)
        assert np.all(region[whole == 1] == 7)
        assert np.all(region[whole == 2] == 8)
        assert np.all(region[whole == 0] == 0)
        assert not np.isin(region, range(1, 7)).any()
        state = regional.default_state(whole.shape[0], session.state)
        assert set(state['assessments']) == set(regional.REGION_IDS)
        assert all(item == {'status': 'unassessed', 'note': ''} for item in state['assessments'].values())
        assert state['protocol']['status'] == 'pending_expert_protocol'
        assert state['research_approved'] is False


def test_six_fixed_region_dictionary_and_partition(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        regions, regional_uncertain, state = region_state(session, whole)
        regions = partition_all(whole)
        regional.validate(whole, regions, regional_uncertain, state, session.state)
        counts = regional.completeness(whole, regions, regional_uncertain, state)
        assert set(regional.REGION_LABEL_MAPPING) == {str(v) for v in range(9)}
        assert counts['assigned_voxels'] == counts['whole_voxels']
        assert counts['unassigned_voxels'] == 0 and counts['assigned_partition_complete']
        assert len(counts['by_region']) == 6
        assert all(item['voxels'] > 0 for item in counts['by_region'].values())


@pytest.mark.parametrize('error', ['outside', 'cross_parent', 'missing', 'value', 'float', 'crop', 'uncertainty_outside', 'uncertainty_value'])
def test_invalid_regions_rejected(setup, error):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        regions, regional_uncertain, state = region_state(session, whole)
        if error == 'outside': regions[0, 0, 0] = 1
        if error == 'cross_parent': regions[3, 10, 10] = 4
        if error == 'missing': regions[3, 10, 10] = 0
        if error == 'value': regions[3, 10, 10] = 9
        if error == 'float': regions = regions.astype(float)
        if error == 'crop': regions = regions[:, :, :-1]
        if error == 'uncertainty_outside': regional_uncertain[0, 0, 0] = 1
        if error == 'uncertainty_value': regional_uncertain[3, 10, 10] = 2
        with pytest.raises(ValidationError):
            regional.validate(whole, regions, regional_uncertain, state)
        with pytest.raises(ValidationError):
            session.save(whole, uncertain, writer, regions=regions, regional_uncertainty=regional_uncertain, regional_state=state)


def test_whole_changes_reconcile_partition_and_parent_specific_review(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        before, uncertain = labelled(session)
        regions, regional_uncertain, state = region_state(session, before)
        regions = partition_all(before)
        for row in state['review']: row.update(medial_reviewed=True, lateral_reviewed=True)
        regional_uncertain[3, 10, 10] = 1
        after = before.copy()
        after[3, 10, 10] = 0              # deleted tissue, region + uncertainty clipped
        after[3, 11, 10] = 2              # compartment correction, becomes lateral unassigned
        after[7, 12, 12] = 1              # new tissue, starts medial unassigned
        fixed, fixed_uncertain, updated = regional.reconcile(after, regions, regional_uncertain, state, previous_whole=before)
        assert fixed[3, 10, 10] == fixed_uncertain[3, 10, 10] == 0
        assert fixed[3, 11, 10] == 8 and fixed[7, 12, 12] == 7
        assert not updated['review'][3]['medial_reviewed']
        assert not updated['review'][3]['lateral_reviewed']
        assert not updated['review'][7]['medial_reviewed']
        assert updated['review'][7]['lateral_reviewed']
        assert updated['review'][5]['medial_reviewed'] and updated['review'][5]['lateral_reviewed']
        assert all(row['medial_reviewed'] for row in state['review']) # input state untouched


def test_reconcile_native_undo_preserves_restored_valid_region(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        restored, uncertain = labelled(session)
        prior = restored.copy(); prior[3, 10, 10] = 0
        region = partition_all(restored)
        expected = region[3, 10, 10]
        state = regional.default_state(restored.shape[0], session.state)
        fixed, _, _ = regional.reconcile(restored, region, np.zeros_like(restored), state, previous_whole=prior)
        assert fixed[3, 10, 10] == expected and 1 <= expected <= 3


def test_invalidate_region_review_does_not_modify_primary(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        primary = copy.deepcopy(session.state)
        state = regional.default_state(session.case.n_slices, session.state)
        state['review'][3].update(medial_reviewed=True, lateral_reviewed=True, flag=True, note='attention')
        updated = regional.invalidate_review(state, [np.int64(3)], ('medial',))
        assert not updated['review'][3]['medial_reviewed']
        assert updated['review'][3]['lateral_reviewed'] and updated['review'][3]['flag']
        assert updated['review'][3]['note'] == 'attention'
        assert session.state == primary


def test_absent_empty_supported_but_absent_assignment_rejected(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        state['assessments']['medial_anterior'] = {'status': 'absent', 'note': 'Synthetic declaration, no invented tissue'}
        regional.validate(whole, region, regional_uncertain, state)
        region[3, 10, 10] = 1
        with pytest.raises(ValidationError, match='declared absent'): regional.validate(whole, region, regional_uncertain, state)


@pytest.mark.parametrize('change', ['protocol', 'research_approved', 'approval', 'status', 'source_identity', 'annotator', 'job_identity', 'mapping', 'review'])
def test_metadata_cannot_promote_or_change_attribution(setup, change):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        if change == 'protocol': state['protocol']['status'] = 'released'
        elif change == 'research_approved': state['research_approved'] = True
        elif change == 'approval': state['approval'] = {'approved': True}
        elif change == 'status': state['status'] = 'approved'
        elif change == 'mapping': state['label_mapping']['1'] = 'lateral anterior horn'
        elif change == 'review': state['review'].pop()
        else: state[change] = 'changed'
        with pytest.raises(ValidationError):
            regional.validate(whole, region, regional_uncertain, state, session.state)


def test_pending_protocol_never_produces_training_validity(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        region = partition_all(whole)
        for item in state['assessments'].values(): item['status'] = 'present'
        for row in state['review']: row.update(medial_reviewed=True, lateral_reviewed=True)
        validity = regional.validity(whole, uncertain, region, regional_uncertain, state, session.state)
        assert validity.dtype == np.uint8 and not validity.any()
        errors = regional.completion_errors(whole, uncertain, region, regional_uncertain, state, session.state)
        assert len(errors) == 1 and 'expert' in errors[0]


@pytest.mark.parametrize('case_index', [0, 1])
def test_native_save_reload_hashes_and_full_geometry(setup, case_index):
    source, ds, store = setup
    source_before = file_hashes(source)
    c = ds.cases[case_index]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        region = partition_all(whole)
        regional_uncertain[3, 10, 10] = 1
        state['review'][2].update(medial_reviewed=True, lateral_reviewed=True, note='Synthetic empty-slice review')
        checkpoint = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        manifest = json.loads((checkpoint/'manifest.json').read_text())
        assert len(manifest['files_sha256']) == 12
        assert set(manifest['files_sha256']) >= regional.REGIONAL_FILES
        assert manifest['regional_extension']['research_approved'] is False
        for filename, expected in [('regions.nii.gz', region), ('regional_uncertainty.nii.gz', regional_uncertain), ('regional_validity.nii.gz', np.zeros_like(whole))]:
            image = nib.load(checkpoint/filename)
            assert image.shape == c.shape_xyz and np.allclose(image.affine, c.affine_ras, atol=1e-5)
            assert image.header.get_xyzt_units()[0] == 'mm'
            assert np.array_equal(np.asarray(image.dataobj).transpose(2, 1, 0), expected)
    with store.open_case(c) as restored:
        actual_regions, actual_uncertain, metadata = restored.load_regions()
        assert np.array_equal(actual_regions, region) and np.array_equal(actual_uncertain, regional_uncertain)
        assert metadata['review'][2]['medial_reviewed'] and metadata['review'][2]['note']
        assert restored.state['annotator'] == 'Synthetic Regional Reader'
    assert file_hashes(source) == source_before


def test_old_checkpoint_open_does_not_rewrite_or_change_job_state(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        checkpoint = session.save(whole, uncertain, writer)
        historical = file_hashes(checkpoint)
        primary = copy.deepcopy(session.state)
    with store.open_case(ds.cases[0]) as resumed:
        regions, regional_uncertain, metadata = resumed.load_regions()
        assert resumed.state == primary
        assert np.array_equal(regions, regional.initialize(whole)) and not regional_uncertain.any()
        assert metadata['job_identity'] == primary['job_identity']
        assert metadata['annotator'] == primary['annotator']
    assert file_hashes(checkpoint) == historical
    assert 'regional_extension' not in json.loads((checkpoint/'manifest.json').read_text())
    assert len(historical) == 8


def test_whole_only_save_has_eligibility_but_no_regional_extension(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        session.load_regions() # merely requesting defaults does not change legacy save API
        checkpoint = session.save(whole, uncertain, writer)
        manifest = json.loads((checkpoint/'manifest.json').read_text())
        assert 'regional_extension' not in manifest and len(manifest['files_sha256']) == 7


def test_legacy_caller_carries_existing_regions_and_invalidates_on_parent_edit(setup):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        regions, regional_uncertain, state = region_state(session, whole)
        regions = partition_all(whole)
        for row in state['review']: row.update(medial_reviewed=True, lateral_reviewed=True)
        first = session.save(whole, uncertain, writer, regions=regions, regional_uncertainty=regional_uncertain, regional_state=state)
    with store.open_case(c) as resumed:
        new_whole, new_uncertain, _ = resumed.load()
        new_whole[3, 10, 10] = 0
        resumed.mark_changed([3])
        checkpoint = resumed.save(new_whole, new_uncertain, writer)
        assert checkpoint != first
        regions, regional_uncertain, state = resumed.load_regions()
        assert regions[3, 10, 10] == 0
        assert not state['review'][3]['medial_reviewed'] and state['review'][3]['lateral_reviewed']
        assert regions[3, 10, 11] == partition_all(whole)[3, 10, 11]


def test_regional_only_save_preserves_primary_approval_and_exports_latest_draft(setup, tmp_path):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        finish_primary(session)
        original = session.save(whole, uncertain, writer, approve=True, practice=True)
        original_hash = file_hashes(original)
        approved = copy.deepcopy(session.state['approval'])
        region, regional_uncertain, state = session.load_regions()
        region[3, 10, 10] = 1
        state['notes'] = 'New regional draft after whole approval'
        latest = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        assert latest != original and session.state['status'] == 'practice_approved'
        assert session.state['approval'] == approved
        assert file_hashes(original) == original_hash
    result = export_approved(store, tmp_path/'Regional results', include_practice=True)
    with zipfile.ZipFile(result) as archive:
        receipt = json.loads(archive.read('results.json'))['cases'][0]
        assert receipt['checkpoint'] == latest.name
        assert receipt['regional_extension']['research_approved'] is False
        assert 'pending' in receipt['regional_annotation_status']
        assert json.loads(archive.read(receipt['folder']+'/regions.json'))['notes'] == state['notes']
        assert not np.asarray(nib.Nifti1Image.from_bytes(__import__('gzip').decompress(archive.read(receipt['folder']+'/regional_validity.nii.gz'))).dataobj).any()


@pytest.mark.parametrize('change', ['labels', 'uncertainty', 'notes', 'review', 'compartments'])
def test_primary_changes_with_region_extension_still_create_primary_draft(setup, change):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        finish_primary(session)
        session.save(whole, uncertain, writer, approve=True, practice=True)
        region, regional_uncertain, state = session.load_regions()
        if change == 'labels':
            whole[3, 10, 10] = 0
            region, regional_uncertain, state = regional.reconcile(whole, region, regional_uncertain, state)
        elif change == 'uncertainty': uncertain[3, 10, 10] = 1
        elif change == 'notes': session.state['notes'] = 'Primary note changed'
        elif change == 'review': session.state['review'][3]['reviewed'] = False
        elif change == 'compartments': session.state['compartments']['medial'] = False
        session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        assert session.state['status'] == 'needs_review' and session.state['approval'] is None


def test_regional_corruption_recovers_previous_complete_checkpoint(setup):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        first = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        region[3, 10, 10] = 1
        second = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        (second/'regions.nii.gz').write_bytes(b'corrupt')
    with store.open_case(c) as resumed:
        assert resumed.recovered and resumed.current_checkpoint == first
        assert resumed.load_regions()[0][3, 10, 10] == 7


def test_region_partial_save_failure_leaves_prior_version(setup, monkeypatch):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        first = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        original_write = core.write_native
        def fault(path, array, case, marker=None):
            if path.name == 'regional_uncertainty.nii.gz': raise OSError(errno.ENOSPC, 'Simulated disk full')
            return original_write(path, array, case, marker)
        monkeypatch.setattr(core, 'write_native', fault)
        with pytest.raises(ValidationError, match='previous saved version is intact'):
            session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        assert store._checkpoints(session.folder) == [first]


def test_partial_regional_arguments_rejected(setup):
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        with pytest.raises(ValidationError, match='all three'):
            session.save(whole, uncertain, writer, regions=regional.initialize(whole))


def test_regional_reader_excludes_pending_even_fully_assigned_and_reviewed(setup):
    from tools.read_regional_annotation import read_regional_annotation
    _, ds, store = setup
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        region = partition_all(whole)
        for row in state['review']: row.update(medial_reviewed=True, lateral_reviewed=True)
        for item in state['assessments'].values(): item['status'] = 'present'
        finish_primary(session)
        checkpoint = session.save(whole, uncertain, writer, approve=True, practice=True, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        result = read_regional_annotation(checkpoint, source_image=session.case.image_path)
        assert result['source_bytes_verified']
        assert result['accepted_regional_voxels'] == 0 and not result['regional_validity'].any()
        assert np.all(result['training_targets'] == -1)
        assert np.array_equal(result['regions'], region)
        assert any('protocol' in reason for reason in result['exclusion_reasons'])
        assert any('practice' in reason for reason in result['exclusion_reasons'])


def test_regional_reader_export_zip_and_wrong_source_rejection(setup, tmp_path):
    from tools.read_regional_annotation import read_regional_annotation
    _, ds, store = setup
    case = ds.cases[1]
    with store.open_case(case) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        region[3, 10, 10] = 1
        regional_uncertain[3, 10, 11] = 1
        # Pending regional uncertainty does not prevent independent whole approval.
        finish_primary(session)
        checkpoint = session.save(whole, uncertain, writer, approve=True, practice=True, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
    result_zip = export_approved(store, tmp_path/'Reader results', include_practice=True)
    loaded = read_regional_annotation(result_zip, case.key)
    assert np.array_equal(loaded['regions'], region)
    assert np.array_equal(loaded['regional_uncertainty'], regional_uncertain)
    assert loaded['accepted_regional_voxels'] == 0
    assert loaded['source_bytes_verified'] is False
    assert np.all(loaded['training_targets'] == -1)
    with pytest.raises(ValidationError, match='wrong checksum'):
        read_regional_annotation(checkpoint, source_image=ds.cases[0].image_path)


@pytest.mark.parametrize('tamper', ['regional_validity.nii.gz', 'regions.nii.gz', 'regional_review.csv', 'regions.json'])
def test_rehashed_regional_semantic_errors_still_block_checkpoint(setup, tamper):
    _, ds, store = setup
    c = ds.cases[0]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        checkpoint = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        path = checkpoint/tamper
        if tamper == 'regional_validity.nii.gz':
            invalid = np.zeros_like(whole); invalid[3, 10, 10] = 1
            core.write_native(path, invalid, c)
        elif tamper == 'regions.nii.gz':
            region[3, 10, 10] = 4
            core.write_native(path, region, c)
        elif tamper == 'regional_review.csv':
            path.write_text(path.read_text().replace('not_reviewed', 'reviewed', 1))
        else:
            value = json.loads(path.read_text()); value['research_approved'] = True
            path.write_text(json.dumps(value))
        manifest = json.loads((checkpoint/'manifest.json').read_text())
        manifest['files_sha256'][tamper] = sha256(path)
        (checkpoint/'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValidationError): store._validate_checkpoint(checkpoint, c)


def test_regional_bad_native_transform_rejected_after_hash_recompute(setup):
    _, ds, store = setup
    c = ds.cases[1]
    with store.open_case(c) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        checkpoint = session.save(whole, uncertain, writer, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        path = checkpoint/'regions.nii.gz'
        image = nib.load(path)
        changed = nib.Nifti1Image(np.asanyarray(image.dataobj), image.affine)
        changed.header.set_xyzt_units('mm')
        changed.set_qform(image.affine, 1)
        shifted = image.affine.copy(); shifted[1, 3] += 2
        changed.set_sform(shifted, 1)
        nib.save(changed, path)
        manifest = json.loads((checkpoint/'manifest.json').read_text())
        manifest['files_sha256']['regions.nii.gz'] = sha256(path)
        (checkpoint/'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValidationError, match='conflict'): store._validate_checkpoint(checkpoint, c)


def test_research_whole_approval_is_independent_from_pending_regions(setup, tmp_path):
    _, ds, _ = setup
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': ds.identity,
           'annotator': 'Synthetic Assigned Reader',
           'protocol': {'version': 'SYNTHETIC-WHOLE-RELEASED-TEST', 'status': 'released'}}
    store = WorkStore(tmp_path/'Independent whole research simulation', ds, job=job)
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        finish_primary(session)
        checkpoint = session.save(whole, uncertain, writer, approve=True, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        assert session.state['status'] == 'approved'
        assert np.asarray(nib.load(checkpoint/'validity.nii.gz').dataobj).all()
        assert not np.asarray(nib.load(checkpoint/'regional_validity.nii.gz').dataobj).any()
        assert session.state['job_identity'] == core.canonical(job)
        assert session.regional_state['research_approved'] is False
    result = export_approved(store, tmp_path/'Independent whole results')
    with zipfile.ZipFile(result) as archive:
        metadata = json.loads(archive.read('results.json'))
        assert metadata['practice_only'] is False
        assert metadata['cases'][0]['regional_extension']['research_approved'] is False
        assert 'Whole approval is independent' in metadata['regional_annotation_contract']


def test_software_practice_region_attribution_and_both_validity_are_zero(setup, tmp_path):
    _, ds, _ = setup
    actor = core.PRACTICE_ACTORS['automated']
    job = {'schema_version': 'meniscus_job/1', 'dataset_identity': ds.identity,
           'protocol': {'version': 'SYNTHETIC-SOFTWARE-PRACTICE', 'status': 'draft'},
           'practice_context': {'purpose': 'software_practice', 'actor_type': 'automated', 'actor': actor}}
    store = WorkStore(tmp_path/'Automated regional QA', ds, job=job)
    with store.open_case(ds.cases[0]) as session:
        whole, uncertain = labelled(session)
        region, regional_uncertain, state = region_state(session, whole)
        finish_primary(session)
        checkpoint = session.save(whole, uncertain, writer, approve=True, practice=True, regions=region, regional_uncertainty=regional_uncertain, regional_state=state)
        assert session.regional_state['annotator'] == actor
        assert session.regional_state['practice_context'] == job['practice_context']
        assert not np.asarray(nib.load(checkpoint/'validity.nii.gz').dataobj).any()
        assert not np.asarray(nib.load(checkpoint/'regional_validity.nii.gz').dataobj).any()
        assert session.state['approval']['human_anatomical_approval'] is False
        assert session.state['approval']['accepted_research_annotation'] is False
