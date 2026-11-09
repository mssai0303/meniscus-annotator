"""Installed headless technical persistence checks; no GUI/drawing claim.

Uses procedural inputs, the installed module and Slicer's actual segmentation
storage. Kept outside the reader startup route and never locates participant MRI.
"""
import json
import os
from pathlib import Path
import platform
import sys
import traceback
import zipfile

import nibabel as nib
import numpy as np
import SimpleITK as sitk
import slicer

INSTALL = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ['MENISCUS_CORE_CHECK_OUTPUT']).resolve()
REPORT = {'passed': False, 'checks': [],
          'platform': platform.platform(),
          'scope': 'Installed bundled-runtime headless technical correction/persistence/export with procedural inputs and actual Slicer segmentation storage; no GUI, interactive drawing, anatomical, or offline workflow acceptance.'}


def check(name, condition):
    REPORT['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    expected = INSTALL / 'lib' / 'Slicer-5.12' / 'qt-scripted-modules'
    sys.path.insert(0, str(expected))
    import MeniscusAnnotatorLib
    from MeniscusAnnotatorLib import core
    check('application helpers loaded from the installed payload',
          Path(core.__file__).resolve().is_relative_to(expected.resolve()))
    sys.path.insert(0, str(INSTALL / 'TestKit'))
    from make_correction_synthetic import make_correction_synthetic
    source = make_correction_synthetic(OUTPUT / 'Synthetic correction inputs', automated=True)
    # Ordinary draft-protocol practice, separate from a software-practice job.
    # Only this generated disposable job is changed; never reader/source data.
    job_path = source / 'correction_job.json'
    job = json.loads(job_path.read_text())
    job.pop('practice_context')
    job_path.write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    before = {p.relative_to(source).as_posix(): core.sha256(p) for p in source.rglob('*') if p.is_file()}
    dataset = core.Dataset(source)
    store = core.WorkStore(OUTPUT / 'Separate synthetic reader work', dataset,
                          core.load_job_config(job_path, dataset), reader='Software QA (headless persistence)')
    distribution = json.loads((INSTALL / 'distribution.json').read_text())
    REPORT.update(application_version=MeniscusAnnotatorLib.APP_VERSION,
                  application_commit=distribution['application_commit'],
                  application_source_sha256=distribution['application_source_sha256'],
                  slicer_version=slicer.app.applicationVersion,
                  slicer_revision=slicer.app.repositoryRevision,
                  SimpleITK=sitk.Version_VersionString())
    approvals = {}
    for case in dataset.cases:
        volume = slicer.util.loadVolume(str(case.image_path))
        check(case.key + ' source loads in native Slicer storage', volume is not None)
        with store.open_case(case) as session:
            session.state['runtime'] = {
                'slicer_version': slicer.app.applicationVersion,
                'slicer_revision': slicer.app.repositoryRevision,
                'application_version': MeniscusAnnotatorLib.APP_VERSION,
                'application_commit': distribution['application_commit'],
                'application_source_sha256': distribution['application_source_sha256'],
                'test_identity': 'Software QA (headless persistence)',
                'interaction_scope': 'technical synthetic core/storage test; not GUI or anatomical review'}
            labels, uncertainty, _ = session.load()
            check(case.key + ' correction initializes both fixed labels', set(np.unique(labels)) == {0, 1, 2})
            labels[0, 5, 6] = 1
            session.mark_changed([0])

            def writer(path):
                node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'SYNTHETIC technical checkpoint')
                node.SetReferenceImageGeometryParameterFromVolumeNode(volume)
                try:
                    for name, array in [('medial', labels == 1), ('lateral', labels == 2), ('uncertain', uncertainty != 0)]:
                        node.GetSegmentation().AddEmptySegment(name, name)
                        segment = node.GetSegmentation().GetSegment(name)
                        segment.SetTag('annotation_purpose', 'protocol_practice')
                        segment.SetTag('research_eligible', 'false')
                        slicer.util.updateSegmentBinaryLabelmapFromArray(array.astype(np.uint8), node, name, volume)
                    storage = node.CreateDefaultStorageNode()
                    slicer.mrmlScene.AddNode(storage)
                    node.SetAndObserveStorageNodeID(storage.GetID())
                    storage.SetCropToMinimumExtent(False)
                    check(case.key + ' editable Slicer segmentation written', slicer.util.saveNode(node, str(path)))
                    reopened = slicer.util.loadSegmentation(str(path))
                    try:
                        for name, array in [('medial', labels == 1), ('lateral', labels == 2), ('uncertain', uncertainty != 0)]:
                            check(case.key + ' editable segment reopens exactly ' + name,
                                  np.array_equal(slicer.util.arrayFromSegmentBinaryLabelmap(reopened, name, volume), array))
                    finally:
                        slicer.mrmlScene.RemoveNode(reopened)
                finally:
                    slicer.mrmlScene.RemoveNode(node)

            first = session.save(labels, uncertainty, writer)
            first_hashes = {p.name: core.sha256(p) for p in first.iterdir()}
            for index in range(3):
                session.mark_reviewed(index)
                session.save_review_journal(labels, uncertainty)
            check(case.key + ' review journal preserves immutable checkpoint',
                  first_hashes == {p.name: core.sha256(p) for p in first.iterdir()})
        with store.open_case(case) as session:
            restored, restored_uncertainty, _ = session.load()
            check(case.key + ' cold session restores exact voxels and journal review',
                  np.array_equal(restored, labels) and np.array_equal(restored_uncertainty, uncertainty)
                  and all(row['reviewed'] for row in session.state['review'][:3]))
            for index in range(case.n_slices):
                session.mark_reviewed(index)
            session.state['compartments'] = {'medial': True, 'lateral': True}
            approved = session.save(labels, uncertainty, writer, approve=True, practice=True)
            check(case.key + ' ordinary draft is practice approved only',
                  session.state['status'] == 'practice_approved'
                  and session.state['annotation_purpose'] == 'protocol_practice'
                  and session.state['research_eligible'] is False)
            approval = json.loads(json.dumps(session.state['approval']))
            check(case.key + ' repeated review is unchanged', not session.mark_reviewed(0))
            session.save(labels, uncertainty, writer)
            check(case.key + ' unchanged save preserves approval', session.state['approval'] == approval)
            approvals[case.key] = (session.current_checkpoint.name, labels.copy())
            source_geometry = sitk.ReadImage(str(case.image_path))
            result_geometry = sitk.ReadImage(str(approved / 'labels.nii.gz'))
            check(case.key + ' independent SimpleITK geometry and full extent match',
                  source_geometry.GetSize() == result_geometry.GetSize()
                  and np.allclose(source_geometry.GetSpacing(), result_geometry.GetSpacing(), atol=1e-6)
                  and np.allclose(source_geometry.GetOrigin(), result_geometry.GetOrigin(), atol=1e-5)
                  and np.allclose(source_geometry.GetDirection(), result_geometry.GetDirection(), atol=1e-6))
            check(case.key + ' practice headers and research eligibility are explicit',
                  b'PRACTICE' in bytes(nib.load(str(approved / 'labels.nii.gz')).header['descrip'])
                  and not np.asarray(nib.load(str(approved / 'research_eligibility.nii.gz')).dataobj).any())
        slicer.mrmlScene.RemoveNode(volume)
    result = core.export_approved(store, OUTPUT / 'Separate return packages', include_practice=True)
    with zipfile.ZipFile(result) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('export unmistakably identifies ordinary protocol practice',
              result.name.startswith('PRACTICE_ONLY-') and manifest['practice_only'] is True)
        for entry in manifest['cases']:
            checkpoint, expected_array = approvals[entry['case_key']]
            check(entry['case_key'] + ' archive contains intended approved checkpoint', entry['checkpoint'] == checkpoint)
            destination = OUTPUT / ('reopened-' + str(len(REPORT['checks'])) + '.nii.gz')
            destination.write_bytes(archive.read(entry['folder'] + '/labels.nii.gz'))
            check(entry['case_key'] + ' returned NIfTI voxels and fixed label values match',
                  np.array_equal(np.asarray(nib.load(str(destination)).dataobj).transpose(2, 1, 0), expected_array)
                  and set(np.unique(expected_array)) <= {0, 1, 2})
    # New unapproved content may never silently return that earlier approval.
    case = dataset.cases[0]
    volume = slicer.util.loadVolume(str(case.image_path))
    with store.open_case(case) as session:
        labels, uncertainty, _ = session.load()
        labels[0, 5, 7] = 1
        session.mark_changed([0])
        session.save(labels, uncertainty, writer)
    plan = core.export_plan(store, include_practice=True)
    check('newer unapproved work requires explicit export-version choice',
          any(row['case_key'] == case.key for row in plan['requires_choice']))
    try:
        core.export_approved(store, OUTPUT / 'Must not silently export', include_practice=True)
    except core.ValidationError:
        check('ordinary export refuses silent older approval', True)
    else:
        raise AssertionError('Older approval was silently exported')
    check('all synthetic original inputs remain byte-for-byte unchanged',
          before == {p.relative_to(source).as_posix(): core.sha256(p) for p in source.rglob('*') if p.is_file()})
    REPORT['passed'] = True


try:
    main()
except Exception:
    REPORT['error'] = traceback.format_exc()
    print(REPORT['error'], flush=True)
finally:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    (OUTPUT.parent / 'headless-persistence-check.json').write_text(json.dumps(REPORT, indent=2) + '\n', encoding='utf-8')
    slicer.app.exit(0 if REPORT['passed'] else 1)
