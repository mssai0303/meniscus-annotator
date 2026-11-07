"""Software-only two-case correction persistence check inside actual Slicer.

Requires MENISCUS_CORRECTION_PRACTICE_CONFIG pointing to a PRIVATE JSON with
dataset, job, work, report and original_predictions [{path, sha256}]. No real
annotation is approved and no source files are modified. No UI redesign.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

import numpy as np
import slicer
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from MeniscusAnnotatorLib.core import Dataset, WorkStore, load_job_config, sha256


def run():
    config = json.loads(Path(os.environ['MENISCUS_CORRECTION_PRACTICE_CONFIG']).read_text())
    report_path = Path(config['report'])
    try:
        dataset = Dataset(config['dataset'])
        job = load_job_config(config['job'], dataset, require_full_correction=True)
        assert job['practice_context'] == {'purpose': 'software_practice', 'actor': 'Software QA (automated)', 'actor_type': 'automated'}
        assert len(dataset.cases) == 2
        before = {str(p): sha256(p) for p in dataset.root.rglob('*') if p.is_file()}
        for item in config['original_predictions']:
            assert sha256(item['path']) == item['sha256']
            before[item['path']] = item['sha256']
        store = WorkStore(config['work'], dataset, job=job)
        results = []
        for case in dataset.cases:
            with store.open_case(case) as session:
                labels, uncertain, _ = session.load()
                assert session.state['initialization']['method'] == 'correction'
                original = labels.copy()
                positives = np.argwhere(labels > 0)
                assert len(positives)
                position = tuple(int(v) for v in positives[len(positives) // 2])
                labels[position] = 0  # One software-test erase, not an anatomical correction.
                session.mark_changed([position[0]])
                volume = slicer.util.loadVolume(str(case.image_path))
                assert volume is not None
                volume.SetSaveWithScene(False)
                matrix = vtk.vtkMatrix4x4(); volume.GetIJKToRASMatrix(matrix)
                loaded_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
                assert np.allclose(loaded_affine, case.affine_ras, rtol=0, atol=1e-4)
                segmentation = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'SOFTWARE PRACTICE ONLY')
                segmentation.SetSaveWithScene(False)
                segmentation.CreateDefaultDisplayNodes()
                segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
                storage = segmentation.CreateDefaultStorageNode()
                slicer.mrmlScene.AddNode(storage)
                segmentation.SetAndObserveStorageNodeID(storage.GetID())
                storage.SetCropToMinimumExtent(False)
                for name, value in [('medial', 1), ('lateral', 2), ('uncertain', None)]:
                    segmentation.GetSegmentation().AddEmptySegment(name, name)
                    array = uncertain if value is None else (labels == value).astype(np.uint8)
                    slicer.util.updateSegmentBinaryLabelmapFromArray(array, segmentation, name, volume)
                checkpoint = session.save(labels, uncertain, lambda path: slicer.util.saveNode(segmentation, str(path)), approve=False)
                assert session.state['annotator'] == 'Software QA (automated)' and session.state['approver'] is None
                assert all(not row['reviewed'] for row in session.state['review'])
            with store.open_case(case) as reopened:
                actual, actual_uncertain, seg_path = reopened.load()
                assert np.array_equal(actual, labels) and np.array_equal(actual_uncertain, uncertain)
                assert np.count_nonzero(actual != original) == 1
                assert reopened.state['approval'] is None and reopened.state['annotation_purpose'] == 'software_practice'
                master = slicer.util.loadSegmentation(str(seg_path))
                assert master is not None
                for name, value in [('medial', 1), ('lateral', 2), ('uncertain', None)]:
                    actual_segment = slicer.util.arrayFromSegmentBinaryLabelmap(master, name, volume)
                    expected = uncertain if value is None else labels == value
                    assert np.array_equal(actual_segment != 0, expected != 0)
                preserved = store.case_folder(case) / ('starting-mask-' + job['cases'][case.key]['starting_mask']['sha256'] + '.nii.gz')
                assert sha256(preserved) == job['cases'][case.key]['starting_mask']['sha256']
            results.append({'case_key': case.key, 'single_voxel_software_edit_reopened': True, 'editable_segmentation_reopened': True, 'research_annotation_approved': False, 'all_slice_reviews_still_unreviewed': True})
            slicer.mrmlScene.RemoveNode(master); slicer.mrmlScene.RemoveNode(segmentation); slicer.mrmlScene.RemoveNode(volume)
        assert all(sha256(path) == expected for path, expected in before.items())
        report = {'passed': True, 'software_practice_only': True, 'cases': results, 'source_files_and_original_predictions_unchanged': True, 'no_Jeff_attribution_or_research_approval': True, 'platform': sys.platform, 'slicer_version': slicer.app.applicationVersion}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        slicer.app.exit(0)
    except Exception as exc:
        report_path.write_text(json.dumps({'passed': False, 'error': type(exc).__name__, 'traceback': traceback.format_exc()}, indent=2) + '\n')
        slicer.app.exit(1)


run()
