"""One-case SOFTWARE PRACTICE correction test in actual Slicer.

All case identifiers, inputs, work, settings, expected arrays and reports come
from a private MENISCUS_REAL_PRACTICE_CONFIG. No anatomical annotation is accepted.
Run phase edit and then cold in separate Slicer processes. The UI is unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import traceback
import zipfile

import numpy as np
import qt
import SimpleITK as sitk
import slicer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from MeniscusAnnotatorLib.core import Dataset, canonical, export_approved, sha256

config = json.loads(Path(os.environ['MENISCUS_REAL_PRACTICE_CONFIG']).read_text())
phase = os.environ.get('MENISCUS_RESOLUTION_QA_PHASE', 'edit')
report = {'phase': phase, 'platform': platform.platform(),
          'slicer_version': slicer.app.applicationVersion,
          'scope': 'AUTOMATED SOFTWARE PRACTICE ONLY; no Jeff or anatomical approval',
          'checks': []}


def check(name, value):
    report['checks'].append({'name': name, 'passed': bool(value)})
    if not value:
        raise AssertionError(name)


def events():
    slicer.app.processEvents()


def matrix_array(matrix):
    return np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])


def erase(widget, value):
    before = widget.collectArrays()[0].copy()
    points = np.argwhere(before == value)
    k, j, i = map(int, points[len(points) // 2])
    widget.goSlice(k)
    widget._resetView()
    widget.setLabel('medial' if value == 1 else 'lateral')
    widget.setTool('Erase')
    widget.brushSize.setValue(2.)
    events()
    red = slicer.app.layoutManager().sliceWidget('Red')
    world = widget.session.case.affine_ras @ np.array([i, j, k, 1])
    xy = np.linalg.inv(matrix_array(red.mrmlSliceNode().GetXYToRAS())) @ world
    interactor = red.sliceView().interactorStyle().GetInteractor()
    interactor.SetEventInformation(int(round(xy[0])), int(round(xy[1])), 0, 0)
    for event in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
        interactor.InvokeEvent(event)
    events()
    after = widget.collectArrays()[0]
    changed = np.argwhere(after != before)
    check('native erase existing label ' + str(value),
          len(changed) > 0 and set(changed[:, 0]) == {k}
          and np.all(before[after != before] == value)
          and np.all(after[after != before] == 0))


try:
    source = Path(config['input_root']).resolve()
    work = Path(config['work_root']).resolve()
    results = Path(config['results_root']).resolve()
    reports = Path(config['report_root']).resolve()
    check('private output locations outside source and Git',
          all(not p.is_relative_to(source) and not p.is_relative_to(REPO)
              for p in (work, results, reports)))
    manifest = json.loads(Path(config['input_manifest']).read_text())
    before = {n: sha256(source / n) for n in manifest['files_sha256']}
    check('isolated inputs match frozen manifest', before == manifest['files_sha256'])
    dataset = Dataset(source)
    key = config['case_key']
    check('only authorized case in isolated copy', set(dataset.by_key) == {key})
    base_job = json.loads(Path(config['job_path']).read_text())
    check('explicit automated software actor', base_job['practice_context'] == {
        'purpose': 'software_practice', 'actor': 'Software QA (automated)', 'actor_type': 'automated'})
    ui_hash = sha256(REPO / 'MeniscusAnnotator.py')
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    widget.settings = qt.QSettings(config['settings_file'], qt.QSettings.IniFormat)
    widget.openDataset(str(source), work_root=str(work))
    widget.openCase(key)
    events()
    case = widget.session.case
    initial = sitk.GetArrayFromImage(sitk.ReadImage(str(case.folder / 'starting_mask.nii.gz')))
    check('correction initialization and unchanged global base identity',
          widget.session.state['initialization']['method'] == 'correction'
          and widget.session.state['job_identity'] == canonical(base_job))
    check('separate case resolution binding retained',
          bool(widget.session.state['initialization'].get('case_resolution')))
    check('complete native MRI loaded',
          widget.volume.GetImageData().GetDimensions() == case.shape_xyz)
    expected_path = Path(config['expected_arrays'])
    if phase == 'edit':
        check('starting mask loaded exactly', np.array_equal(widget.collectArrays()[0], initial))
        for value in (1, 2):
            erase(widget, value)
        edited, uncertainty = widget.collectArrays()
        check('small edits differ from prediction', not np.array_equal(edited, initial))
        widget.notes.setPlainText('AUTOMATED SOFTWARE QA: arbitrary erases, no anatomical assessment.')
        widget.save()
        widget.closeCase()
        check('normal close releases case', widget.session is None)
        widget.openCase(key)
        events()
        check('save close reopen retains exact edit',
              np.array_equal(widget.collectArrays()[0], edited)
              and np.array_equal(widget.collectArrays()[1], uncertainty))
        # Review flags below exercise the software-only export guard. The fixed
        # actor records an unaccepted automated check and validity stays all zero.
        for k in range(case.n_slices):
            widget.goSlice(k)
            widget.reviewButton.click()
            events()
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        widget.save(approve=True, practice=True)
        state = widget.session.state
        check('no expert or research approval',
              state['approval']['accepted_research_annotation'] is False
              and state['approval']['human_anatomical_approval'] is False
              and state['annotator'] == 'Software QA (automated)')
        np.savez_compressed(expected_path, labels=edited, uncertainty=uncertainty)
        archive_path = export_approved(widget.store, results, case_keys=[key], include_practice=True)
        with zipfile.ZipFile(archive_path) as archive:
            summary = json.loads(archive.read('results.json'))
            check('software export ZIP and role', archive.testzip() is None
                  and summary['software_practice'] is True
                  and summary['accepted_research_annotation'] is False)
            entry = summary['cases'][0]
            check('only this case exported', len(summary['cases']) == 1 and entry['case_key'] == key)
            for name, expected in [('labels.nii.gz', edited), ('uncertainty.nii.gz', uncertainty),
                                   ('validity.nii.gz', np.zeros_like(edited))]:
                temp = reports / ('export-' + name)
                temp.write_bytes(archive.read(entry['folder'] + '/' + name))
                image = sitk.ReadImage(str(temp))
                check('exact exported voxels ' + name, np.array_equal(sitk.GetArrayFromImage(image), expected))
                check('native exported geometry ' + name,
                      image.GetSize() == case.shape_xyz
                      and np.allclose(image.GetSpacing(), case.metadata['spacing_xyz_mm'])
                      and np.allclose(image.GetOrigin(), case.metadata['origin_lps_mm'])
                      and np.allclose(np.array(image.GetDirection()).reshape(3, 3), case.metadata['direction_lps_columns']))
            metadata = json.loads(archive.read(entry['folder'] + '/annotation.json'))
            check('export retains resolution and original global binding',
                  metadata['initialization'].get('case_resolution')
                  and metadata['job_identity'] == canonical(base_job))
    elif phase == 'cold':
        expected = np.load(expected_path)
        check('fresh process restored exact edit',
              np.array_equal(widget.collectArrays()[0], expected['labels'])
              and np.array_equal(widget.collectArrays()[1], expected['uncertainty']))
        check('fresh process remains unaccepted software work',
              widget.session.state['approval']['accepted_research_annotation'] is False)
    else:
        raise ValueError('Unsupported phase')
    widget.closeCase()
    check('source files unchanged after work',
          before == {n: sha256(source / n) for n in before})
    check('UI source unchanged', sha256(REPO / 'MeniscusAnnotator.py') == ui_hash)
    report['passed'] = True
except Exception:
    report['passed'] = False
    report['private_error'] = traceback.format_exc()
finally:
    output = Path(config['report_root']) / ('slicer-' + phase + '.json')
    output.write_text(json.dumps(report, indent=2) + '\n')
    print('ONE_CASE_RESOLUTION_SOFTWARE_QA=' + str(report['passed']), flush=True)
    slicer.app.exit(0 if report['passed'] else 1)
