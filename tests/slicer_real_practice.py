"""Private, actual-Slicer SOFTWARE PRACTICE checks on two authorised real scans.

No participant identifiers or MRI paths belong in this source. Supply a private
MENISCUS_REAL_PRACTICE_CONFIG JSON. All data, reports, screenshots and QA outputs
must remain outside the repository and original source package. Marks in this
test are arbitrary software probes, never anatomical reference annotations.
"""
import datetime
import json
import os
from pathlib import Path
import platform
import re
import sys
import traceback
import zipfile

import nibabel as nib
import numpy as np
import qt
import SimpleITK as sitk
import slicer
import vtk

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from MeniscusAnnotatorLib import Dataset, ValidationError, export_approved, sha256

CONFIG_PATH = Path(os.environ['MENISCUS_REAL_PRACTICE_CONFIG']).resolve()
CONFIG = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
if CONFIG.get('schema_version') != 'meniscus_real_practice_test/1':
    raise ValueError('Unsupported private practice-test configuration.')
PHASE = os.environ.get('MENISCUS_REAL_PHASE', 'workflow')
REPORT_DIR = Path(CONFIG['report_root']).resolve()
SOURCE = Path(CONFIG['source_root']).resolve()
INPUTS = Path(CONFIG['input_root']).resolve()
WORK = Path(CONFIG['work_root']).resolve()
RESULTS = Path(CONFIG['results_root']).resolve()
SETTINGS = Path(CONFIG['settings_file']).resolve()
JOB_PATH = Path(CONFIG['job_path']).resolve()


def within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


for protected in (REPORT_DIR, WORK, RESULTS, SETTINGS.parent):
    if within(protected, REPO) or within(protected, SOURCE) or within(protected, INPUTS):
        raise ValueError('Practice outputs must be outside source inputs and Git.')
REPORT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.chmod(0o700)
SETTINGS.parent.mkdir(parents=True, exist_ok=True)
REPORT = {'phase': PHASE, 'scope': 'AUTOMATED SOFTWARE PRACTICE ONLY; arbitrary voxel marks, no anatomical assessment, no accepted research annotation, no Jeff approval',
          'platform': platform.platform(), 'machine': platform.machine(),
          'slicer_version': slicer.app.applicationVersion,
          'slicer_revision': slicer.app.repositoryRevision, 'checks': [],
          'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}


def write_private(path, data):
    path = Path(path)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    path.chmod(0o600)


def check(name, passed, detail=None):
    result = {'name': name, 'passed': bool(passed)}
    if detail is not None:
        result['detail'] = detail
    REPORT['checks'].append(result)
    write_private(REPORT_DIR / 'private-progress.json', {'phase': PHASE, 'checks_completed': len(REPORT['checks']), 'last_check': name, 'last_check_passed': bool(passed)})
    if not passed:
        raise AssertionError(name)


def events():
    slicer.app.processEvents()


def red():
    return slicer.app.layoutManager().sliceWidget('Red')


def array_matrix(matrix):
    return np.array([[matrix.GetElement(r, c) for c in range(4)] for r in range(4)])


def plane_index(widget):
    point = array_matrix(red().mrmlSliceNode().GetSliceToRAS())[:, 3]
    return float((np.linalg.inv(widget.session.case.affine_ras) @ point)[2])


def xy_for_ijk(widget, ijk):
    world = widget.session.case.affine_ras @ np.array([*ijk, 1])
    inverse = np.linalg.inv(array_matrix(red().mrmlSliceNode().GetXYToRAS()))
    point = inverse @ world
    return int(round(point[0])), int(round(point[1]))


def interactor_at(widget, ijk, control=0):
    x, y = xy_for_ijk(widget, ijk)
    interactor = red().sliceView().interactorStyle().GetInteractor()
    interactor.SetEventInformation(x, y, control, 0)
    return interactor, x, y


def stroke(widget, ijk, label='medial', tool='Paint'):
    widget.setLabel(label)
    widget.setTool(tool)
    widget.brushSize.setValue(2.)
    interactor, _, _ = interactor_at(widget, ijk)
    for name in ['EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent']:
        interactor.InvokeEvent(name)
    events()


def draw(widget, vertices):
    widget.setLabel('medial')
    widget.setTool('Draw')
    for ijk in vertices:
        interactor, _, _ = interactor_at(widget, ijk)
        interactor.InvokeEvent('LeftButtonPressEvent')
        interactor.InvokeEvent('LeftButtonReleaseEvent')
    interactor.InvokeEvent('RightButtonPressEvent')
    interactor.InvokeEvent('RightButtonReleaseEvent')
    events()


def wheel(widget, ijk, control=0, backward=False):
    interactor, _, _ = interactor_at(widget, ijk, control)
    interactor.InvokeEvent('MouseWheelBackwardEvent' if backward else 'MouseWheelForwardEvent')
    interactor.SetControlKey(0)
    events()


def drag(widget, ijk, button, dx, dy):
    interactor, x, y = interactor_at(widget, ijk)
    interactor.InvokeEvent(button + 'ButtonPressEvent')
    for step in range(1, 5):
        interactor.SetEventInformation(x + int(dx * step / 4), y + int(dy * step / 4), 0, 0)
        interactor.InvokeEvent('MouseMoveEvent')
    interactor.InvokeEvent(button + 'ButtonReleaseEvent')
    events()


def source_manifest():
    manifest = json.loads(Path(CONFIG['source_manifest']).read_text(encoding='utf-8'))
    files = manifest.get('files_sha256', manifest.get('files'))
    if not isinstance(files, dict) or not files:
        raise ValueError('Private original-source manifest requires files_sha256.')
    return files


def verify_original():
    files = source_manifest()
    for relative, expected in files.items():
        path = SOURCE / relative
        if not within(path, SOURCE) or sha256(path) != expected:
            raise AssertionError('An original source file differs from the frozen private manifest.')
    return len(files)


def verify_saved_case(widget, path, labels, uncertainty, prefix):
    case = widget.session.case
    expected = [('labels.nii.gz', labels), ('uncertainty.nii.gz', uncertainty), ('validity.nii.gz', np.zeros_like(labels, dtype=np.uint8))]
    for filename, array in expected:
        image = sitk.ReadImage(str(Path(path) / filename))
        meta = case.metadata
        check(prefix + ' independent exact voxels ' + filename, np.array_equal(sitk.GetArrayFromImage(image), array))
        check(prefix + ' full dimensions ' + filename, image.GetSize() == case.shape_xyz)
        check(prefix + ' spacing ' + filename, np.allclose(image.GetSpacing(), meta['spacing_xyz_mm'], atol=1e-5))
        check(prefix + ' origin ' + filename, np.allclose(image.GetOrigin(), meta['origin_lps_mm'], atol=1e-4))
        check(prefix + ' direction ' + filename, np.allclose(np.array(image.GetDirection()).reshape(3, 3), meta['direction_lps_columns'], atol=1e-5))
        independent = nib.load(str(Path(path) / filename))
        q, qc = independent.header.get_qform(coded=True)
        s, sc = independent.header.get_sform(coded=True)
        check(prefix + ' explicit units/transforms ' + filename, independent.header.get_xyzt_units()[0] == 'mm' and qc > 0 and sc > 0 and np.allclose(q, s, atol=1e-4))
        check(prefix + ' source affine ' + filename, np.allclose(independent.affine, case.affine_ras, atol=1e-4))
    check(prefix + ' fixed anatomical label values', set(np.unique(labels)).issubset({0, 1, 2}))
    check(prefix + ' binary separate uncertainty', set(np.unique(uncertainty)).issubset({0, 1}))
    reopened = slicer.util.loadSegmentation(str(Path(path) / 'segmentation.seg.nrrd'))
    try:
        for segment_id, expected in [('medial', labels == 1), ('lateral', labels == 2), ('uncertain', uncertainty > 0)]:
            actual = slicer.util.arrayFromSegmentBinaryLabelmap(reopened, segment_id, widget.volume)
            check(prefix + ' editable native segmentation ' + segment_id, np.array_equal(actual > 0, expected))
    finally:
        helpers = [reopened.GetDisplayNode(), reopened.GetStorageNode()]
        slicer.mrmlScene.RemoveNode(reopened)
        for helper in helpers:
            if helper:
                slicer.mrmlScene.RemoveNode(helper)


def open_widget():
    check('private selection explicitly verified', CONFIG.get('selection_verified') is True)
    dataset = Dataset(INPUTS)
    keys = CONFIG['selected_case_keys']
    check('exactly two permitted source identities', len(keys) == 2 and set(dataset.by_key) == set(keys))
    job = json.loads(JOB_PATH.read_text(encoding='utf-8'))
    practice = job.get('practice_context', {})
    check('automated actor is explicit and not Jeff', practice == {'purpose': 'software_practice', 'actor': 'Software QA (automated)', 'actor_type': 'automated'})
    check('practice protocol remains draft', job['protocol']['status'] == 'draft' and job['dataset_identity'] == dataset.identity)
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    widget.settings = qt.QSettings(str(SETTINGS), qt.QSettings.IniFormat)
    widget.settings.setValue('Meniscus/job/' + dataset.identity, str(JOB_PATH))
    widget.openDataset(str(INPUTS), work_root=str(WORK))
    events()
    return widget, keys


def confirm_practice_approval(widget):
    # Only the SOFTWARE PRACTICE job can reach this point. This is an automated
    # confirmation of the workflow dialog, never a human/anatomical approval.
    attempts = [0]
    def yes():
        attempts[0] += 1
        dialog = qt.QApplication.activeModalWidget()
        if dialog and hasattr(dialog, 'button'):
            button = dialog.button(qt.QMessageBox.Yes)
            if button:
                button.click()
                return
        if attempts[0] < 100:
            qt.QTimer.singleShot(25, yes)
        elif dialog:
            dialog.reject()
    qt.QTimer.singleShot(0, yes)
    widget.approveButton.click()
    events()


def run_workflow():
    count = verify_original()
    check('original source bytes match frozen manifest before test', count > 0)
    copied_hashes = {str(p.relative_to(INPUTS)): sha256(p) for p in INPUTS.rglob('*') if p.is_file()}
    widget, keys = open_widget()
    REPORT['cases'] = []
    approved_arrays = {}
    for ordinal, key in enumerate(keys, 1):
        prefix = 'case ' + str(ordinal)
        widget.openCase(key)
        events()
        case = widget.session.case
        meta = case.metadata
        dims = case.shape_xyz
        i, j, k = dims[0] // 2, dims[1] // 2, dims[2] // 2
        REPORT['cases'].append({'case_key': key, 'participant_id': meta['participant_id'], 'visit_month': meta['visit_month'],
                                'side': meta['knee_side'], 'shape_xyz': dims, 'spacing_xyz_mm': meta['spacing_xyz_mm'],
                                'direction_lps_columns': meta['direction_lps_columns'], 'source_image_sha256': meta['image_sha256']})
        header = str(widget.identityLabel.text)
        check(prefix + ' participant visit and side shown honestly', meta['participant_id'] in header and ('M%03d' % meta['visit_month']) in header and ('Left' if meta['knee_side'] == 'L' else 'Right') in header)
        check(prefix + ' complete acquired slice range', widget.sliceSlider.minimum == 1 and widget.sliceSlider.maximum == dims[2])
        source_matrix = vtk.vtkMatrix4x4()
        widget.volume.GetIJKToRASMatrix(source_matrix)
        check(prefix + ' source grid retained in Slicer', widget.volume.GetImageData().GetDimensions() == dims and np.allclose(array_matrix(source_matrix), case.affine_ras, atol=1e-4))
        check(prefix + ' initial plane matches display', abs(plane_index(widget) - widget.currentSlice) < 0.001)
        check(prefix + ' source-only blank initialization', not widget.collectArrays()[0].any() and not widget.collectArrays()[1].any())
        check(prefix + ' automated drawings are not attributed to Jeff', widget.session.state['annotator'] == 'Software QA (automated)' and widget.session.state.get('practice_context') == {'purpose': 'software_practice', 'actor': 'Software QA (automated)', 'actor_type': 'automated'})
        labels_text = [str(label.text) for label in slicer.util.mainWindow().findChildren(qt.QLabel) if label.isVisible()]
        check(prefix + ' visible software practice scope', any('SOFTWARE PRACTICE' in text.upper() for text in labels_text))
        for acquired in range(dims[2]):
            widget.sliceSlider.setValue(acquired + 1)
            events()
            text_numbers = [int(value) for value in re.findall(r'\d+', str(widget.sliceReadout.text))]
            check(prefix + ' acquired plane ' + str(acquired + 1), widget.currentSlice == acquired and abs(plane_index(widget) - acquired) < 0.001 and text_numbers[:2] == [acquired + 1, dims[2]])
        for endpoint in [0, dims[2] - 1]:
            widget.goSlice(endpoint)
            before = widget.collectArrays()[0]
            stroke(widget, (i, j, endpoint))
            after = widget.collectArrays()[0]
            changed = np.argwhere(before != after)
            check(prefix + ' endpoint single-acquired-slice Paint ' + str(endpoint + 1), len(changed) > 0 and set(changed[:, 0]) == {endpoint})
            widget.editor.undo()
            events()
            check(prefix + ' endpoint Undo exact ' + str(endpoint + 1), np.array_equal(widget.collectArrays()[0], before))
        widget.goSlice(k)
        widget.setTool('')
        events()
        wheel(widget, (i, j, k))
        check(prefix + ' mouse wheel moves one acquired slice', abs(widget.currentSlice - k) == 1)
        wheel(widget, (i, j, widget.currentSlice), backward=True)
        check(prefix + ' reverse wheel returns to original acquired slice', widget.currentSlice == k)
        before_fov = np.array(red().mrmlSliceNode().GetFieldOfView())
        wheel(widget, (i, j, k), control=1)
        after_fov = np.array(red().mrmlSliceNode().GetFieldOfView())
        check(prefix + ' Ctrl wheel zoom changes field of view', not np.allclose(before_fov[:2], after_fov[:2]) and widget.currentSlice == k)
        before_pan = array_matrix(red().mrmlSliceNode().GetXYToRAS())
        drag(widget, (i, j, k), 'Middle', 30, 20)
        after_pan = array_matrix(red().mrmlSliceNode().GetXYToRAS())
        check(prefix + ' middle drag pans without changing acquired slice', not np.allclose(before_pan[:3, 3], after_pan[:3, 3]) and widget.currentSlice == k)
        display = widget.volume.GetDisplayNode()
        panel = widget.windowLevelButton.parentWidget()
        if hasattr(panel, 'collapsed'): panel.collapsed = False
        events()
        before_contrast_labels = widget.collectArrays()[0].copy()
        widget.windowLevelButton.click()
        events()
        interaction = slicer.app.applicationLogic().GetInteractionNode()
        check(prefix + ' explicit window level mode is visible and native', widget.windowLevelButton.isVisible() and interaction.GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.AdjustWindowLevel and 'Window/level' in str(widget.toolText.text))
        old_wl = np.array([display.GetWindow(), display.GetLevel()])
        drag(widget, (i, j, k), 'Left', 50, 25)
        new_wl = np.array([display.GetWindow(), display.GetLevel()])
        check(prefix + ' explicit window level left drag changes contrast only', not np.allclose(old_wl, new_wl) and widget.currentSlice == k and np.array_equal(widget.collectArrays()[0], before_contrast_labels))
        widget.setTool('Paint')
        check(prefix + ' drawing restores native view interaction mode', interaction.GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.ViewTransform and not widget.windowLevelButton.checked)
        if hasattr(panel, 'collapsed'): panel.collapsed = True
        widget._resetView()
        events()
        check(prefix + ' Reset view preserves acquired slice', abs(plane_index(widget) - k) < 0.001)
        before = widget.collectArrays()[0]
        stroke(widget, (i - 15, j, k), 'medial')
        medial = widget.collectArrays()[0]
        changed = np.argwhere(before != medial)
        check(prefix + ' medial Paint intended voxels and acquired slice', medial[k, j, i - 15] == 1 and set(changed[:, 0]) == {k})
        stroke(widget, (i + 15, j, k), 'lateral')
        both = widget.collectArrays()[0]
        check(prefix + ' lateral fixed mapping separate from medial', both[k, j, i + 15] == 2 and both[k, j, i - 15] == 1)
        widget.editor.undo()
        events()
        check(prefix + ' label Undo exact', np.array_equal(widget.collectArrays()[0], medial))
        widget.editor.redo()
        events()
        check(prefix + ' label Redo exact', np.array_equal(widget.collectArrays()[0], both))
        stroke(widget, (i + 15, j, k), 'lateral', 'Erase')
        erased = widget.collectArrays()[0]
        check(prefix + ' Erase removes intended label', erased[k, j, i + 15] == 0 and erased[k, j, i - 15] == 1)
        widget.editor.undo()
        events()
        check(prefix + ' Erase Undo restores label', np.array_equal(widget.collectArrays()[0], both))
        draw(widget, [(i - 8, j - 18, k), (i + 8, j - 18, k), (i + 8, j - 8, k), (i - 8, j - 8, k)])
        drawn = widget.collectArrays()[0]
        check(prefix + ' native Draw contour fills current plane', drawn[k, j - 12, i] == 1 and set(np.argwhere(drawn != both)[:, 0]) == {k})
        widget.visible.setChecked(False)
        check(prefix + ' annotation hide control works', not widget.anatomy.GetDisplayNode().GetVisibility())
        widget.visible.setChecked(True)
        widget.fill.setChecked(False)
        check(prefix + ' outline-only display works', widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0 and widget.anatomy.GetDisplayNode().GetOpacity2DOutline() > 0)
        widget.fill.setChecked(True)
        widget.opacity.setValue(35)
        check(prefix + ' transparent fill opacity works', abs(widget.anatomy.GetDisplayNode().GetOpacity2DFill() - .35) < .001)
        stroke(widget, (i - 15, j, k), 'uncertain')
        labels, uncertain = widget.collectArrays()
        check(prefix + ' uncertainty remains separate and overlapping', uncertain[k, j, i - 15] == 1 and labels[k, j, i - 15] == 1 and set(np.unique(labels)).issubset({0, 1, 2}))
        widget.reviewButton.click()
        events()
        check(prefix + ' explicit review and next records current slice', widget.session.state['review'][k]['reviewed'] and widget.currentSlice == k + 1)
        widget.goSlice(k)
        stroke(widget, (i - 25, j + 15, k), 'medial')
        check(prefix + ' edit invalidates reviewed slice', not widget.session.state['review'][k]['reviewed'])
        widget.attention.setChecked(True)
        check(prefix + ' attention flag independent of review', widget.session.state['review'][k]['flag'] and not widget.session.state['review'][k]['reviewed'])
        labels, uncertain = widget.collectArrays()
        check(prefix + ' unresolved uncertainty blocks practice approval', bool(widget.session.approval_errors(labels, uncertain, practice=True)))
        widget.notes.setPlainText('AUTOMATED SOFTWARE QA: arbitrary voxel marks, no anatomical assessment, not Jeff\'s annotations. Case ' + str(ordinal))
        widget.saveButton.click()
        events()
        saved_labels, saved_uncertain = widget.collectArrays()
        saved_checkpoint = widget.session.current_checkpoint
        verify_saved_case(widget, saved_checkpoint, saved_labels, saved_uncertain, prefix + ' saved')
        check(prefix + ' save feedback reports saved', 'Saved' in str(widget.saveStatus.text))
        other = keys[ordinal % len(keys)]
        widget.openCase(other)
        events()
        widget.openCase(key)
        widget.goSlice(k)
        events()
        reopened_labels, reopened_uncertain = widget.collectArrays()
        check(prefix + ' case switch restores exact annotations', np.array_equal(reopened_labels, saved_labels) and np.array_equal(reopened_uncertain, saved_uncertain))
        check(prefix + ' case switch restores notes and review flags', 'AUTOMATED SOFTWARE QA' in widget.session.state['notes'] and widget.session.state['review'][k]['flag'])
        stroke(widget, (i - 15, j, k), 'uncertain', 'Erase')
        check(prefix + ' uncertainty can be resolved separately', not widget.collectArrays()[1].any())
        widget.attention.setChecked(False)
        # Every reviewed record is exercised through the actual review UI button.
        for acquired in range(dims[2]):
            widget.goSlice(acquired)
            widget.reviewButton.click()
            events()
        check(prefix + ' explicit software review covers every acquired slice', all(row['reviewed'] and not row['flag'] for row in widget.session.state['review']))
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        labels, uncertain = widget.collectArrays()
        check(prefix + ' arbitrary QA points retain fixed compartment mapping after review', labels[k,j,i-15] == 1 and labels[k,j,i+15] == 2 and labels[k,0,0] == 0)
        check(prefix + ' research approval stays blocked in software practice', bool(widget.session.approval_errors(labels, uncertain, practice=False)))
        check(prefix + ' practice approval permitted after required records', not widget.session.approval_errors(labels, uncertain, practice=True))
        confirm_practice_approval(widget)
        state = widget.session.state
        check(prefix + ' software practice approval is not Jeff approval', state['status'] == 'practice_approved' and state['annotator'] == state['approver'] == 'Software QA (automated)' and state['approval']['approval_type'] == 'automated_software_check' and not state['approval']['deliberate_approval_required_by_ui'])
        verify_saved_case(widget, widget.session.current_checkpoint, labels, uncertain, prefix + ' approved software practice')
        approved_arrays[key] = (labels.copy(), uncertain.copy())
        window = slicer.util.mainWindow()
        for width, height in [(1280, 800), (1440, 900)]:
            window.resize(width, height)
            events()
            check(prefix + ' navigation controls visible at ' + str(width), widget.sliceSlider.isVisible() and widget.sliceReadout.isVisible() and widget.sliceSlider.width >= 100)
        window.grab().save(str(REPORT_DIR / ('private-case-' + str(ordinal) + '.png')))
        (REPORT_DIR / ('private-case-' + str(ordinal) + '.png')).chmod(0o600)
    finish_workflow(widget, keys, approved_arrays, copied_hashes, count)


def finish_workflow(widget, keys, approved_arrays, copied_hashes, count):
    widget.closeCase()
    rejected = False
    try:
        export_approved(widget.store, RESULTS, include_practice=False)
    except ValidationError:
        rejected = True
    check('ordinary research export excludes software practice', rejected)
    archive_path = export_approved(widget.store, RESULTS, include_practice=True)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('practice export is clearly segregated', manifest['practice_only'] is True and manifest.get('software_practice') is True and archive_path.name.startswith('SOFTWARE_PRACTICE_ONLY-'))
        check('both and only selected cases exported', {item['case_key'] for item in manifest['cases']} == set(keys))
        check('export omits source MRI images', not any(name.endswith('/image.nii.gz') for name in archive.namelist()))
        check('export ZIP integrity', archive.testzip() is None)
        for ordinal, item in enumerate(manifest['cases'], 1):
            metadata = json.loads(archive.read(item['folder'] + '/annotation.json'))
            check('export actor ' + str(ordinal), metadata['annotator'] == metadata['approver'] == 'Software QA (automated)' and metadata['practice_context']['purpose'] == 'software_practice' and metadata['approval']['accepted_research_annotation'] is False and metadata['approval']['human_anatomical_approval'] is False)
            case = widget.dataset.by_key[item['case_key']]
            expected_labels, expected_uncertainty = approved_arrays[item['case_key']]
            for filename, expected in [('labels.nii.gz', expected_labels), ('uncertainty.nii.gz', expected_uncertainty), ('validity.nii.gz', np.zeros_like(expected_labels, dtype=np.uint8))]:
                temporary = REPORT_DIR / ('export-check-' + str(ordinal) + '-' + filename)
                temporary.write_bytes(archive.read(item['folder'] + '/' + filename))
                image = sitk.ReadImage(str(temporary))
                independent = nib.load(str(temporary))
                q, qc = independent.header.get_qform(coded=True)
                sf, sc = independent.header.get_sform(coded=True)
                check('export explicit native NIfTI forms and units ' + str(ordinal) + filename, independent.shape == case.shape_xyz and independent.header.get_xyzt_units()[0] == 'mm' and qc > 0 and sc > 0 and np.allclose(q, sf, atol=1e-4) and np.allclose(independent.affine, case.affine_ras, atol=1e-4))
                check('export exact approved voxels ' + str(ordinal) + filename, np.array_equal(sitk.GetArrayFromImage(image), expected))
                check('export complete source geometry ' + str(ordinal) + filename, image.GetSize() == case.shape_xyz and np.allclose(image.GetSpacing(), case.metadata['spacing_xyz_mm'], atol=1e-5) and np.allclose(image.GetOrigin(), case.metadata['origin_lps_mm'], atol=1e-4) and np.allclose(np.array(image.GetDirection()).reshape(3, 3), case.metadata['direction_lps_columns'], atol=1e-5))
                check('export integer label classes ' + str(ordinal) + filename, np.issubdtype(sitk.GetArrayFromImage(image).dtype, np.integer) and set(np.unique(sitk.GetArrayFromImage(image))).issubset({0, 1, 2} if filename == 'labels.nii.gz' else ({0} if filename == 'validity.nii.gz' else {0, 1})))
                temporary.unlink()
    check('private input copies unchanged', copied_hashes == {str(p.relative_to(INPUTS)): sha256(p) for p in INPUTS.rglob('*') if p.is_file()})
    check('all original source bytes unchanged after workflow', verify_original() == count)
    widget.openCase(keys[-1])
    widget.goSlice(widget.session.case.n_slices // 2)
    widget.notes.setPlainText('AUTOMATED SOFTWARE QA: close and fresh-process persistence probe; not anatomical review and not Jeff approval.')
    expected, expected_uncertainty = widget.collectArrays()
    np.savez_compressed(REPORT_DIR / 'private-resume-expected.npz', labels=expected, uncertainty=expected_uncertainty)
    write_private(REPORT_DIR / 'private-resume-expectation.json', {'case_key': keys[-1], 'slice_index': widget.currentSlice, 'notes': str(widget.notes.toPlainText())})
    slicer.util.mainWindow().close()
    events()
    check('normal window close releases case lock', widget.session is None)


def run_finish():
    # Continue only after the explicitly identified old-prefix test expectation.
    # Real edit/navigation checks already passed; do not repeat those operations.
    previous = json.loads((REPORT_DIR / 'private-workflow-workflow.json').read_text(encoding='utf-8'))
    prior_checks = previous['checks']
    if not prior_checks or prior_checks[-1]['name'] != 'practice export is clearly segregated' or prior_checks[-1]['passed'] or not all(item['passed'] for item in prior_checks[:-1]):
        raise AssertionError('Export continuation requires the preserved, otherwise-passing native workflow.')
    REPORT['checks'] = prior_checks[:-1]
    REPORT['cases'] = previous.get('cases', [])
    REPORT['inherited_passed_native_checks'] = len(REPORT['checks'])
    REPORT['continuation_reason'] = 'Corrected the test prefix expectation to SOFTWARE_PRACTICE_ONLY; application output was correctly segregated. Earlier source/scene interaction checks are retained, not repeated.'
    widget, keys = open_widget()
    approved_arrays = {}
    frozen = source_manifest()
    for ordinal, key in enumerate(keys, 1):
        case = widget.dataset.by_key[key]
        for source_file in [case.image_path, case.folder / 'case.json', case.folder / 'slice_review.csv']:
            relative = str(source_file.relative_to(INPUTS))
            check('exact private copy still matches original file ' + str(ordinal) + ' ' + source_file.name, frozen.get(relative) == sha256(source_file))
        found = None
        for checkpoint in widget.store._checkpoints(widget.store.case_folder(case)):
            state, labels, uncertain = widget.store._validate_checkpoint(checkpoint, case)
            if state['status'] == 'practice_approved':
                found = (labels, uncertain)
                break
        check('preserved practice approval exists ' + str(ordinal), found is not None)
        approved_arrays[key] = found
    copied_hashes = {str(p.relative_to(INPUTS)): sha256(p) for p in INPUTS.rglob('*') if p.is_file()}
    count = verify_original()
    finish_workflow(widget, keys, approved_arrays, copied_hashes, count)


def run_resume():
    widget, keys = open_widget()
    expected = json.loads((REPORT_DIR / 'private-resume-expectation.json').read_text(encoding='utf-8'))
    widget._resume()
    events()
    check('fresh process restores selected source case', widget.session.case.key == expected['case_key'])
    check('fresh process restores acquired slice', widget.currentSlice == expected['slice_index'] and abs(plane_index(widget) - widget.currentSlice) < .001)
    check('fresh process restores close-saved notes', widget.session.state['notes'] == expected['notes'])
    arrays = np.load(REPORT_DIR / 'private-resume-expected.npz')
    labels, uncertainty = widget.collectArrays()
    check('fresh process restores exact annotations', np.array_equal(labels, arrays['labels']) and np.array_equal(uncertainty, arrays['uncertainty']))
    check('fresh process preserves honest software practice actor', widget.session.state['annotator'] == 'Software QA (automated)' and widget.session.state['practice_context']['purpose'] == 'software_practice')
    verify_saved_case(widget, widget.session.current_checkpoint, labels, uncertainty, 'fresh process')
    check('fresh process leaves original source unchanged', verify_original() > 0)
    widget.closeCase()


def run_orientation_recheck():
    """Recheck the display-only superior-up fix without replacing earlier QA.

    This phase requires fresh automated work. It repeats only the affected native
    view/edit/save/export path, retaining every earlier report and checkpoint.
    """
    REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
    count = verify_original()
    check('orientation original source matches frozen manifest before test', count > 0)
    copied_hashes = {str(p.relative_to(INPUTS)): sha256(p) for p in INPUTS.rglob('*') if p.is_file()}
    widget, keys = open_widget()
    approved_arrays = {}
    REPORT['cases'] = []
    for ordinal, key in enumerate(keys, 1):
        prefix = 'orientation case ' + str(ordinal)
        widget.openCase(key)
        events()
        case = widget.session.case
        dims = case.shape_xyz
        i, j, k = dims[0] // 2, dims[1] // 2, dims[2] // 2
        REPORT['cases'].append({'case_key': key, 'shape_xyz': dims,
                                'direction_lps_columns': case.metadata['direction_lps_columns']})
        expected_normal = case.affine_ras[:3, 2] / np.linalg.norm(case.affine_ras[:3, 2])
        source_up = case.affine_ras[:3, 1] / np.linalg.norm(case.affine_ras[:3, 1])
        expected_up = -source_up if source_up[2] < 0 else source_up
        check(prefix + ' fresh blank automated work', not widget.collectArrays()[0].any() and not widget.collectArrays()[1].any() and widget.session.current_checkpoint is None)
        widget.goSlice(k)
        widget._resetView()
        events()
        matrix = array_matrix(red().mrmlSliceNode().GetSliceToRAS())
        check(prefix + ' superior up with acquired positive K normal', matrix[2, 1] > 0 and np.allclose(matrix[:3, 1], expected_up, atol=1e-6) and np.allclose(matrix[:3, 2], expected_normal, atol=1e-6))
        check(prefix + ' right handed display rotation only', np.isclose(np.linalg.det(matrix[:3, :3]), 1., atol=1e-6) and np.allclose(matrix[:3, 0], np.cross(expected_up, expected_normal), atol=1e-6))
        annotation = red().sliceView().cornerAnnotation()
        check(prefix + ' superior direction label at upper image edge', 'S' in str(annotation.GetText(vtk.vtkCornerAnnotation.UpperEdge)))
        widget.setTool('')
        wheel(widget, (i, j, k))
        check(prefix + ' upright wheel advances one acquired slice', abs(widget.currentSlice - k) == 1)
        wheel(widget, (i, j, widget.currentSlice), backward=True)
        check(prefix + ' upright reverse wheel restores acquired slice', widget.currentSlice == k and abs(plane_index(widget) - k) < .001)
        fov = np.array(red().mrmlSliceNode().GetFieldOfView())
        wheel(widget, (i, j, k), control=1)
        check(prefix + ' upright Ctrl wheel zoom preserves acquired plane', not np.allclose(fov[:2], np.array(red().mrmlSliceNode().GetFieldOfView())[:2]) and widget.currentSlice == k and abs(plane_index(widget) - k) < .001)
        pan = array_matrix(red().mrmlSliceNode().GetXYToRAS())
        drag(widget, (i, j, k), 'Middle', 30, 20)
        check(prefix + ' upright middle drag pans on acquired plane', not np.allclose(pan[:3, 3], array_matrix(red().mrmlSliceNode().GetXYToRAS())[:3, 3]) and widget.currentSlice == k and abs(plane_index(widget) - k) < .001)
        panel = widget.windowLevelButton.parentWidget()
        if hasattr(panel, 'collapsed'):
            panel.collapsed = False
        widget.windowLevelButton.click()
        events()
        display = widget.volume.GetDisplayNode()
        contrast = np.array([display.GetWindow(), display.GetLevel()])
        drag(widget, (i, j, k), 'Left', 50, 25)
        check(prefix + ' upright native window level drag changes contrast only', not np.allclose(contrast, [display.GetWindow(), display.GetLevel()]) and widget.currentSlice == k and not widget.collectArrays()[0].any())
        widget.setTool('Paint')
        check(prefix + ' upright Paint restores interaction mode', slicer.app.applicationLogic().GetInteractionNode().GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.ViewTransform and not widget.windowLevelButton.checked)
        if hasattr(panel, 'collapsed'):
            panel.collapsed = True
        widget._resetView()
        events()
        before = widget.collectArrays()[0].copy()
        stroke(widget, (i - 15, j, k), 'medial')
        medial = widget.collectArrays()[0].copy()
        changed = np.argwhere(before != medial)
        check(prefix + ' upright medial Paint exact IJK only current acquired slice', medial[k, j, i - 15] == 1 and len(changed) > 0 and set(changed[:, 0]) == {k})
        stroke(widget, (i + 15, j, k), 'lateral')
        both = widget.collectArrays()[0].copy()
        check(prefix + ' upright lateral Paint exact IJK and fixed mapping', both[k, j, i + 15] == 2 and both[k, j, i - 15] == 1 and set(np.argwhere(both != medial)[:, 0]) == {k})
        stroke(widget, (i + 15, j, k), 'lateral', 'Erase')
        erased = widget.collectArrays()[0].copy()
        check(prefix + ' upright Erase exact IJK only current acquired slice', erased[k, j, i + 15] == 0 and erased[k, j, i - 15] == 1 and set(np.argwhere(erased != both)[:, 0]) == {k})
        widget.editor.undo()
        events()
        check(prefix + ' upright Erase Undo restores exact voxels', np.array_equal(widget.collectArrays()[0], both))
        widget.editor.redo()
        events()
        check(prefix + ' upright Erase Redo restores exact voxels', np.array_equal(widget.collectArrays()[0], erased))
        widget.editor.undo()
        events()
        check(prefix + ' upright second Undo restores both labels', np.array_equal(widget.collectArrays()[0], both))
        widget.notes.setPlainText('AUTOMATED SOFTWARE QA: superior-up display regression; arbitrary voxel marks only, no anatomical assessment or Jeff approval.')
        widget.saveButton.click()
        events()
        saved_labels, saved_uncertain = widget.collectArrays()
        verify_saved_case(widget, widget.session.current_checkpoint, saved_labels, saved_uncertain, prefix + ' saved')
        widget.closeCase()
        widget.openCase(key)
        widget.goSlice(k)
        events()
        reopened_labels, reopened_uncertain = widget.collectArrays()
        check(prefix + ' upright reopening preserves exact arrays', np.array_equal(reopened_labels, saved_labels) and np.array_equal(reopened_uncertain, saved_uncertain))
        for acquired in range(dims[2]):
            widget.sliceSlider.setValue(acquired + 1)
            widget._resetView()
            events()
            matrix = array_matrix(red().mrmlSliceNode().GetSliceToRAS())
            displayed = [int(value) for value in re.findall(r'\d+', str(widget.sliceReadout.text))]
            check(prefix + ' upright reset acquired plane ' + str(acquired + 1), widget.currentSlice == acquired and abs(plane_index(widget) - acquired) < .001 and displayed[:2] == [acquired + 1, dims[2]] and matrix[2, 1] > 0 and np.allclose(matrix[:3, 2], expected_normal, atol=1e-6))
            # Explicit software-only review records are required by the normal
            # practice approval workflow. They do not validate anatomical labels.
            widget.reviewButton.click()
            events()
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        labels, uncertain = widget.collectArrays()
        check(prefix + ' upright practice approval normal requirements satisfied', not widget.session.approval_errors(labels, uncertain, practice=True))
        confirm_practice_approval(widget)
        check(prefix + ' upright approval remains automated unaccepted software work', widget.session.state['status'] == 'practice_approved' and widget.session.state['approval']['accepted_research_annotation'] is False and widget.session.state['approver'] == 'Software QA (automated)')
        approved_arrays[key] = (labels.copy(), uncertain.copy())
        widget.goSlice(k)
        widget._resetView()
        widget.setTool('')
        slicer.util.mainWindow().resize(1440, 900)
        events()
        screenshot = REPORT_DIR / ('private-upright-case-' + str(ordinal) + '.png')
        slicer.util.mainWindow().grab().save(str(screenshot))
        screenshot.chmod(0o600)
    check('orientation latest UI source unchanged during checks', sha256(REPO / 'MeniscusAnnotator.py') == REPORT['ui_source_sha256'])
    check('orientation latest core source unchanged during checks', sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py') == REPORT['core_source_sha256'])
    finish_workflow(widget, keys, approved_arrays, copied_hashes, count)


def run_status_recheck():
    """Check native overlay redraw after tool changes, without editing a scan."""
    REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
    widget, keys = open_widget()

    def capture(name):
        path = REPORT_DIR / ('private-overlay-' + name + '.png')
        red().sliceView().grab().save(str(path))
        path.chmod(0o600)
        return sha256(path)

    for ordinal, key in enumerate(keys, 1):
        prefix = 'overlay case ' + str(ordinal)
        widget.openCase(key)
        widget.goSlice(widget.session.case.n_slices // 2)
        widget._resetView()
        events()
        original_slice = widget.currentSlice
        before = tuple(array.copy() for array in widget.collectArrays())
        source_files = [widget.session.case.image_path, widget.session.case.folder / 'case.json', widget.session.case.folder / 'slice_review.csv']
        source_hashes = [sha256(path) for path in source_files]
        widget.setLabel('medial')
        widget.setTool('Paint')
        events()
        paint_image = capture(str(ordinal) + '-paint')
        text = str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperRight))
        check(prefix + ' Paint active tool label and overlay agree', widget.activeLabel == 'medial' and widget.editor.activeEffect().name == 'Paint' and widget.toolButtons['Paint'].checked and 'Paint' in str(widget.toolText.text) and 'Paint' in text)
        widget.setTool('')
        events()
        navigate_image = capture(str(ordinal) + '-navigate-immediate')
        text = str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperRight))
        check(prefix + ' Navigate active state and overlay agree without slice change', widget.editor.activeEffect() is None and not any(button.checked for button in widget.toolButtons.values()) and 'Navigate' in str(widget.toolText.text) and 'Navigate' in text and widget.currentSlice == original_slice)
        check(prefix + ' Navigate is immediately different in native rendered image', navigate_image != paint_image)
        red().sliceView().forceRender()
        check(prefix + ' Navigate immediate frame already matches forced native redraw', capture(str(ordinal) + '-navigate-forced') == navigate_image)
        panel = widget.windowLevelButton.parentWidget()
        if hasattr(panel, 'collapsed'):
            panel.collapsed = False
        widget.windowLevelButton.click()
        events()
        window_level_image = capture(str(ordinal) + '-window-level-immediate')
        text = str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperRight))
        interaction = slicer.app.applicationLogic().GetInteractionNode()
        check(prefix + ' Window level state and overlay agree without slice change', widget.windowLevelButton.checked and widget.editor.activeEffect() is None and interaction.GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.AdjustWindowLevel and 'Window/level' in str(widget.toolText.text) and 'Window/level' in text and widget.currentSlice == original_slice)
        check(prefix + ' Window level immediately changes native rendered image', window_level_image != navigate_image)
        red().sliceView().forceRender()
        check(prefix + ' Window level immediate frame already matches forced native redraw', capture(str(ordinal) + '-window-level-forced') == window_level_image)
        widget.setTool('Paint')
        events()
        text = str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperRight))
        check(prefix + ' Paint restores native editing state and overlay', interaction.GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.ViewTransform and not widget.windowLevelButton.checked and widget.editor.activeEffect().name == 'Paint' and 'Paint' in text and 'Window/level' not in text)
        after = widget.collectArrays()
        check(prefix + ' Status changes preserve annotation and acquired plane', all(np.array_equal(a, b) for a, b in zip(before, after)) and widget.currentSlice == original_slice and abs(plane_index(widget) - original_slice) < .001)
        check(prefix + ' Source copy bytes unchanged by status checks', source_hashes == [sha256(path) for path in source_files])
        widget.closeCase()
    check('overlay latest UI source unchanged during checks', sha256(REPO / 'MeniscusAnnotator.py') == REPORT['ui_source_sha256'])
    check('overlay latest core source unchanged during checks', sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py') == REPORT['core_source_sha256'])
    slicer.util.mainWindow().close()
    events()
    check('overlay isolated QA window closes normally', widget.session is None)


try:
    if PHASE == 'workflow':
        run_workflow()
    elif PHASE == 'finish':
        run_finish()
    elif PHASE == 'resume':
        run_resume()
    elif PHASE == 'orientation_recheck':
        run_orientation_recheck()
    elif PHASE == 'status_recheck':
        run_status_recheck()
    else:
        raise ValueError('Unknown private practice-test phase.')
    REPORT['passed'] = all(result['passed'] for result in REPORT['checks'])
except Exception:
    REPORT['passed'] = False
    REPORT['private_error'] = traceback.format_exc()
    try:
        slicer.util.mainWindow().grab().save(str(REPORT_DIR / ('private-failure-' + PHASE + '.png')))
        (REPORT_DIR / ('private-failure-' + PHASE + '.png')).chmod(0o600)
    except Exception:
        pass
finally:
    REPORT['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_private(REPORT_DIR / ('private-workflow-' + PHASE + '.json'), REPORT)
    print('REAL_SOFTWARE_PRACTICE_PHASE=' + PHASE + '; PASSED=' + str(REPORT.get('passed', False)), flush=True)
    slicer.app.exit(0 if REPORT.get('passed') else 1)
