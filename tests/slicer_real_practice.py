"""Private, actual-Slicer SOFTWARE PRACTICE checks on two authorised real scans.

No participant identifiers or MRI paths belong in this source. Supply a private
MENISCUS_REAL_PRACTICE_CONFIG JSON. All data, reports, screenshots and QA outputs
must remain outside the repository and original source package. Marks in this
test are arbitrary software probes, never anatomical reference annotations.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
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
from MeniscusAnnotatorLib.core import resolve_starting_mask_path

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


def correction_start(widget, prefix):
    """Check the explicit permitted prediction and its preserved original."""
    check(prefix + ' correction configuration explicit', CONFIG.get('annotation_mode') == 'correction' and CONFIG.get('require_initial_provenance') is True)
    case = widget.session.case
    rule = widget.store.job['cases'][case.key]
    start = rule.get('starting_mask', {})
    check(prefix + ' correction permission ready', rule.get('annotation_mode') == 'correction' and rule.get('availability', 'ready') == 'ready' and all(start.get(name) for name in ('path', 'source', 'version', 'sha256')))
    source = resolve_starting_mask_path(widget.dataset, start)
    check(prefix + ' permitted starting mask checksum', source.is_file() and sha256(source) == start['sha256'])
    independent = nib.load(str(source))
    q, qc = independent.header.get_qform(coded=True)
    sf, sc = independent.header.get_sform(coded=True)
    initial = np.asarray(independent.dataobj).transpose(2, 1, 0).copy()
    check(prefix + ' permitted mask nonempty fixed compartment values', np.issubdtype(initial.dtype, np.integer) and set(np.unique(initial)) == {0, 1, 2})
    check(prefix + ' permitted mask native geometry and transforms', independent.shape == case.shape_xyz and independent.header.get_xyzt_units()[0] == 'mm' and qc > 0 and sc > 0 and np.allclose(q, sf, atol=1e-4) and np.allclose(independent.affine, case.affine_ras, atol=1e-4))
    independent_sitk = sitk.ReadImage(str(source))
    check(prefix + ' permitted mask independent reader exact voxels', np.array_equal(sitk.GetArrayFromImage(independent_sitk), initial))
    expected_provenance = {name: start[name] for name in ('source', 'version', 'sha256')}
    check(prefix + ' initialization provenance retained', widget.session.state['initialization'] == {'method': 'correction', 'starting_mask': expected_provenance})
    preserved = widget.session.folder / ('starting-mask-' + start['sha256'] + '.nii.gz')
    check(prefix + ' original prediction preserved byte for byte', preserved.is_file() and sha256(preserved) == start['sha256'])
    check(prefix + ' automated correction is not Jeff work', widget.session.state['annotator'] == 'Software QA (automated)' and widget.session.state['annotation_purpose'] == 'software_practice' and widget.session.state['practice_context']['actor_type'] == 'automated')
    return initial


def empty_patch(labels, k):
    """Find a fully empty in-plane fixture area; never assume MRI background."""
    plane = labels[k]
    half = 32
    candidates = [(i, j) for j in range(half + 4, plane.shape[0] - half - 4, 12)
                  for i in range(half + 4, plane.shape[1] - half - 4, 12)]
    candidates.sort(key=lambda point: (point[0] - plane.shape[1] / 2) ** 2 + (point[1] - plane.shape[0] / 2) ** 2)
    for i, j in candidates:
        if not plane[j-half:j+half+1, i-half:i+half+1].any():
            return i, j
    raise AssertionError('No verified empty in-plane patch for arbitrary software probes.')


def run_correction_workflow():
    """Exercise native correction controls on explicitly supplied predictions.

    Test marks are software fixtures. They never establish anatomical validity,
    and practice approval/export continues through the ordinary guarded workflow.
    """
    REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
    count = verify_original()
    check('correction original source matches frozen manifest before test', count > 0)
    copied_hashes = {str(path.relative_to(INPUTS)): sha256(path) for path in INPUTS.rglob('*') if path.is_file()}
    widget, keys = open_widget()
    approved_arrays = {}
    REPORT['cases'] = []
    for ordinal, key in enumerate(keys, 1):
        prefix = 'correction case ' + str(ordinal)
        widget.openCase(key)
        events()
        case = widget.session.case
        dims = case.shape_xyz
        initial = correction_start(widget, prefix + ' initial')
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' exact permitted labels initially displayed', np.array_equal(labels, initial) and not uncertainty.any() and widget.session.current_checkpoint is None)
        meta = case.metadata
        header = str(widget.identityLabel.text)
        check(prefix + ' source identity and complete acquired slices displayed', meta['participant_id'] in header and ('M%03d' % meta['visit_month']) in header and ('Left' if meta['knee_side'] == 'L' else 'Right') in header and widget.sliceSlider.maximum == dims[2])
        REPORT['cases'].append({'case_key': key, 'shape_xyz': dims, 'initial_label_counts': {str(value): int(np.count_nonzero(initial == value)) for value in (1, 2)}, 'initialization': widget.session.state['initialization']})

        for label, value in [('medial', 1), ('lateral', 2)]:
            points = np.argwhere(widget.collectArrays()[0] == value)
            k, j, i = [int(number) for number in points[len(points) // 2]]
            widget.goSlice(k)
            widget._resetView()
            events()
            widget.reviewButton.click()
            widget.goSlice(k)
            events()
            check(prefix + ' explicit software review before ' + label + ' erase', widget.session.state['review'][k]['reviewed'])
            before = widget.collectArrays()[0].copy()
            stroke(widget, (i, j, k), label, 'Erase')
            erased = widget.collectArrays()[0].copy()
            changed = np.argwhere(before != erased)
            check(prefix + ' native ' + label + ' Erase changes existing prediction only on intended acquired slice', erased[k, j, i] == 0 and len(changed) > 0 and set(changed[:, 0]) == {k} and np.all(before[before != erased] == value) and np.all(erased[before != erased] == 0))
            check(prefix + ' native ' + label + ' Erase invalidates reviewed slice', not widget.session.state['review'][k]['reviewed'])
            widget.editor.undo()
            events()
            check(prefix + ' native ' + label + ' Erase Undo exact', np.array_equal(widget.collectArrays()[0], before))
            widget.editor.redo()
            events()
            check(prefix + ' native ' + label + ' Erase Redo exact', np.array_equal(widget.collectArrays()[0], erased))

        k = dims[2] // 2
        labels = widget.collectArrays()[0]
        i, j = empty_patch(labels, k)
        widget.goSlice(k)
        widget._resetView()
        widget.setTool('')
        events()
        wheel(widget, (i, j, k))
        check(prefix + ' native correction wheel moves one acquired slice', abs(widget.currentSlice - k) == 1)
        wheel(widget, (i, j, widget.currentSlice), backward=True)
        check(prefix + ' reverse correction wheel restores acquired slice', widget.currentSlice == k and abs(plane_index(widget) - k) < .001)
        before = widget.collectArrays()[0].copy()
        stroke(widget, (i - 18, j + 12, k), 'medial')
        medial = widget.collectArrays()[0].copy()
        changed = np.argwhere(before != medial)
        check(prefix + ' native medial Paint in verified empty patch', medial[k, j+12, i-18] == 1 and len(changed) > 0 and set(changed[:, 0]) == {k})
        stroke(widget, (i + 18, j + 12, k), 'lateral')
        both = widget.collectArrays()[0].copy()
        changed = np.argwhere(medial != both)
        check(prefix + ' native lateral Paint fixed mapping and acquired slice', both[k, j+12, i+18] == 2 and both[k, j+12, i-18] == 1 and len(changed) > 0 and set(changed[:, 0]) == {k})
        draw(widget, [(i-10, j-14, k), (i+10, j-14, k), (i+10, j-4, k), (i-10, j-4, k)])
        drawn = widget.collectArrays()[0].copy()
        changed = np.argwhere(both != drawn)
        check(prefix + ' native Draw contour in verified empty patch only intended slice', drawn[k, j-9, i] == 1 and len(changed) > 0 and set(changed[:, 0]) == {k})
        widget.editor.undo()
        events()
        check(prefix + ' native Draw Undo exact', np.array_equal(widget.collectArrays()[0], both))
        widget.editor.redo()
        events()
        check(prefix + ' native Draw Redo exact', np.array_equal(widget.collectArrays()[0], drawn))
        stroke(widget, (i-18, j+12, k), 'uncertain')
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' correction uncertainty independent of anatomical labels', np.array_equal(labels, drawn) and uncertainty[k, j+12, i-18] == 1 and set(np.unique(labels)) == {0, 1, 2})
        stroke(widget, (i-18, j+12, k), 'uncertain', 'Erase')
        check(prefix + ' correction uncertainty resolved separately', not widget.collectArrays()[1].any() and np.array_equal(widget.collectArrays()[0], drawn))
        widget.visible.setChecked(False)
        check(prefix + ' correction display visibility toggles', not widget.anatomy.GetDisplayNode().GetVisibility())
        widget.visible.setChecked(True)
        widget.fill.setChecked(False)
        check(prefix + ' correction outline display', widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0 and widget.anatomy.GetDisplayNode().GetOpacity2DOutline() > 0)
        widget.fill.setChecked(True)
        widget.opacity.setValue(35)
        check(prefix + ' correction transparent fill display', abs(widget.anatomy.GetDisplayNode().GetOpacity2DFill() - .35) < .001)
        widget.notes.setPlainText('AUTOMATED SOFTWARE QA: arbitrary native correction-control probes on an existing permitted prediction; no anatomical assessment and not Jeff annotations.')
        widget.saveButton.click()
        events()
        saved_labels, saved_uncertainty = widget.collectArrays()
        check(prefix + ' correction changes differ from original and original remains preserved', not np.array_equal(saved_labels, initial))
        verify_saved_case(widget, widget.session.current_checkpoint, saved_labels, saved_uncertainty, prefix + ' saved')
        correction_start(widget, prefix + ' saved provenance')
        other = keys[ordinal % len(keys)]
        widget.openCase(other)
        widget.openCase(key)
        widget.goSlice(k)
        events()
        reopened_labels, reopened_uncertainty = widget.collectArrays()
        check(prefix + ' case switching restores exact correction arrays', np.array_equal(reopened_labels, saved_labels) and np.array_equal(reopened_uncertainty, saved_uncertainty))
        check(prefix + ' case switching restores software QA notes', 'AUTOMATED SOFTWARE QA' in widget.session.state['notes'])
        correction_start(widget, prefix + ' reopened provenance')
        for acquired in range(dims[2]):
            widget.sliceSlider.setValue(acquired + 1)
            events()
            displayed = [int(value) for value in re.findall(r'\d+', str(widget.sliceReadout.text))]
            check(prefix + ' correction acquired plane ' + str(acquired+1), widget.currentSlice == acquired and abs(plane_index(widget)-acquired) < .001 and displayed[:2] == [acquired+1, dims[2]])
            widget.reviewButton.click()
            events()
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' correction research approval remains blocked', bool(widget.session.approval_errors(labels, uncertainty, practice=False)))
        check(prefix + ' correction practice approval normal requirements satisfied', not widget.session.approval_errors(labels, uncertainty, practice=True))
        confirm_practice_approval(widget)
        state = widget.session.state
        check(prefix + ' correction approval is automated software only', state['status'] == 'practice_approved' and state['annotator'] == state['approver'] == 'Software QA (automated)' and state['approval']['approval_type'] == 'automated_software_check' and not state['approval']['accepted_research_annotation'] and not state['approval']['human_anatomical_approval'])
        verify_saved_case(widget, widget.session.current_checkpoint, labels, uncertainty, prefix + ' approved software practice')
        approved_arrays[key] = (labels.copy(), uncertainty.copy())
    check('correction UI source unchanged during checks', sha256(REPO / 'MeniscusAnnotator.py') == REPORT['ui_source_sha256'])
    check('correction core source unchanged during checks', sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py') == REPORT['core_source_sha256'])
    finish_workflow(widget, keys, approved_arrays, copied_hashes, count)


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


def finish_workflow(widget, keys, approved_arrays, copied_hashes, count, archive_path=None):
    widget.closeCase()
    rejected = False
    try:
        export_approved(widget.store, RESULTS, include_practice=False)
    except ValidationError:
        rejected = True
    check('ordinary research export excludes software practice', rejected)
    if archive_path is None:
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
            if CONFIG.get('annotation_mode') == 'correction':
                start = widget.store.job['cases'][case.key]['starting_mask']
                provenance = {name: start[name] for name in ('source', 'version', 'sha256')}
                check('export correction provenance ' + str(ordinal), metadata['initialization'] == {'method': 'correction', 'starting_mask': provenance})
                check('export original permitted prediction byte identity ' + str(ordinal), hashlib.sha256(archive.read(item['folder'] + '/original-starting-mask.nii.gz')).hexdigest() == start['sha256'])
                check('export permitted prediction source unchanged ' + str(ordinal), sha256(resolve_starting_mask_path(widget.dataset, start)) == start['sha256'])
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
    if CONFIG.get('annotation_mode') == 'correction':
        REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
        REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
        correction_start(widget, 'fresh process correction')
    verify_saved_case(widget, widget.session.current_checkpoint, labels, uncertainty, 'fresh process')
    if CONFIG.get('annotation_mode') == 'correction':
        slicer.util.mainWindow().resize(1440, 900)
        events()
        red().sliceView().forceRender()
        screenshot = REPORT_DIR / 'private-correction-restored.png'
        slicer.util.mainWindow().grab().save(str(screenshot))
        screenshot.chmod(0o600)
    check('fresh process leaves original source unchanged', verify_original() > 0)
    widget.closeCase()


def run_correction_cold_all():
    """Cold-open the correction case not covered by the last-case resume phase.

    Expected arrays come from the approved ZIP already compared with the original
    native workflow's in-memory arrays. No new drawings, reviews or approvals.
    """
    REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
    previous = json.loads((REPORT_DIR / 'private-workflow-correction_workflow.json').read_text(encoding='utf-8'))
    prior_resume = json.loads((REPORT_DIR / 'private-workflow-resume.json').read_text(encoding='utf-8'))
    resumed = json.loads((REPORT_DIR / 'private-resume-expectation.json').read_text(encoding='utf-8'))
    check('cold correction original workflow and last-case resume passed', previous.get('passed') is True and prior_resume.get('passed') is True and all(item['passed'] for item in previous['checks']) and all(item['passed'] for item in prior_resume['checks']))
    check('cold correction same tested UI and core source', previous['ui_source_sha256'] == REPORT['ui_source_sha256'] and previous['core_source_sha256'] == REPORT['core_source_sha256'] and prior_resume['ui_source_sha256'] == REPORT['ui_source_sha256'] and prior_resume['core_source_sha256'] == REPORT['core_source_sha256'])
    widget, keys = open_widget()
    remaining = [key for key in keys if key != resumed['case_key']]
    check('cold correction exactly one case remains after prior last-case resume', resumed['case_key'] == keys[-1] and len(remaining) == 1)
    REPORT['cold_restored_case_keys'] = remaining
    REPORT['previously_cold_restored_case_key'] = resumed['case_key']
    copied_hashes = {str(path.relative_to(INPUTS)): sha256(path) for path in INPUTS.rglob('*') if path.is_file()}
    archives = sorted(RESULTS.glob('SOFTWARE_PRACTICE_ONLY-*.zip'))
    check('cold correction exact prior export available', len(archives) == 1)
    with zipfile.ZipFile(archives[0]) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('cold correction prior export identity and integrity', archive.testzip() is None and manifest['dataset_identity'] == widget.dataset.identity and manifest.get('software_practice') is True and manifest.get('practice_only') is True)
        for ordinal, key in enumerate(remaining, 1):
            prefix = 'cold correction case ' + str(ordinal)
            case = widget.dataset.by_key[key]
            receipts = [item for item in manifest['cases'] if item['case_key'] == key]
            check(prefix + ' exact source receipt in prior export', len(receipts) == 1 and receipts[0]['source_identity'] == case.identity and receipts[0]['source_image_sha256'] == case.metadata['image_sha256'])
            receipt = receipts[0]
            base = receipt['folder'] + '/'
            checkpoint_payload = archive.read(base + 'manifest.json')
            checkpoint_manifest = json.loads(checkpoint_payload)
            check(prefix + ' prior export manifest checksum', hashlib.sha256(checkpoint_payload).hexdigest() == receipt['manifest_sha256'])
            metadata = json.loads(archive.read(base + 'annotation.json'))
            check(prefix + ' prior export automated unaccepted approval', metadata['status'] == 'practice_approved' and metadata['annotator'] == metadata['approver'] == 'Software QA (automated)' and metadata['approval']['accepted_research_annotation'] is False and metadata['approval']['human_anatomical_approval'] is False)
            expected = {}
            for filename in ('labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz'):
                payload = archive.read(base + filename)
                check(prefix + ' prior export payload checksum ' + filename, hashlib.sha256(payload).hexdigest() == checkpoint_manifest['files_sha256'][filename])
                extracted = REPORT_DIR / ('private-cold-expected-' + str(ordinal) + '-' + filename)
                extracted.write_bytes(payload)
                extracted.chmod(0o600)
                image = sitk.ReadImage(str(extracted))
                independent = nib.load(str(extracted))
                expected[filename] = sitk.GetArrayFromImage(image)
                check(prefix + ' prior export source grid ' + filename, image.GetSize() == case.shape_xyz and independent.shape == case.shape_xyz and np.allclose(independent.affine, case.affine_ras, atol=1e-4))
            check(prefix + ' prior export practice validity all zero', not expected['validity.nii.gz'].any())
            folder = widget.store.case_folder(case)
            checkpoints_before = [path.name for path in widget.store._checkpoints(folder)]
            widget.openCase(key)
            events()
            check(prefix + ' actual module opened intended source case', widget.session.case.key == key and widget.session.case.identity == receipt['source_identity'])
            check(prefix + ' actual module restored exact approved checkpoint', widget.session.current_checkpoint.name == receipt['checkpoint'] and widget.session.state['status'] == 'practice_approved')
            labels, uncertainty = widget.collectArrays()
            check(prefix + ' actual module arrays equal prior exact export', np.array_equal(labels, expected['labels.nii.gz']) and np.array_equal(uncertainty, expected['uncertainty.nii.gz']))
            correction_start(widget, prefix + ' provenance')
            check(prefix + ' actual module initialization equals prior export', widget.session.state['initialization'] == metadata['initialization'])
            start = widget.store.job['cases'][key]['starting_mask']
            check(prefix + ' original prediction export checksum', hashlib.sha256(archive.read(base + 'original-starting-mask.nii.gz')).hexdigest() == start['sha256'])
            matrix = vtk.vtkMatrix4x4()
            widget.volume.GetIJKToRASMatrix(matrix)
            check(prefix + ' actual module full native source grid', widget.volume.GetImageData().GetDimensions() == case.shape_xyz and np.allclose(array_matrix(matrix), case.affine_ras, atol=1e-4))
            check(prefix + ' cold native plane aligned with displayed acquired slice', abs(plane_index(widget)-widget.currentSlice) < .001)
            verify_saved_case(widget, widget.session.current_checkpoint, labels, uncertainty, prefix + ' restored')
            widget.closeCase()
            check(prefix + ' no annotation checkpoint created by read-only cold check', [path.name for path in widget.store._checkpoints(folder)] == checkpoints_before)
    check('cold correction private input copies unchanged', copied_hashes == {str(path.relative_to(INPUTS)): sha256(path) for path in INPUTS.rglob('*') if path.is_file()})
    check('cold correction final UI and core source unchanged', sha256(REPO / 'MeniscusAnnotator.py') == REPORT['ui_source_sha256'] and sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py') == REPORT['core_source_sha256'])
    slicer.util.mainWindow().close()
    events()
    check('cold correction QA closes normally', widget.session is None)


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


def ui_open_case(widget, key, prefix):
    rows = [row for row in range(widget.caseTable.rowCount)
            if widget.caseTable.item(row, 0).data(qt.Qt.UserRole) == key]
    check(prefix + ' case appears in actual case list', len(rows) == 1)
    widget.caseTable.setCurrentCell(rows[0], 0)
    widget.caseTable.selectRow(rows[0])
    # An unexpected application error must become a failed private receipt,
    # rather than leaving unattended native QA waiting forever in a modal.
    errors = []
    watcher = qt.QTimer()
    watcher.setInterval(25)
    def dismiss_error():
        dialog = qt.QApplication.activeModalWidget()
        if dialog and str(dialog.windowTitle) in ('Meniscus annotation', 'Save required before closing'):
            errors.append(widget._diagnostic or str(dialog.windowTitle))
            dialog.accept()
    watcher.connect('timeout()', dismiss_error)
    watcher.start()
    try:
        widget.openCaseButton.click()
    finally:
        watcher.stop()
    events()
    check(prefix + ' Open selected case control opens intended source', not errors and widget.session is not None and widget.session.case.key == key, errors or None)


def ui_draw_points(widget, vertices, label):
    widget.labelButtons[label].click()
    widget.toolButtons['Draw'].click()
    events()
    for point in vertices:
        native, _, _ = interactor_at(widget, point)
        for event in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
            native.InvokeEvent(event)
        events()


def ui_close_contour(widget, point):
    native, _, _ = interactor_at(widget, point)
    native.InvokeEvent('RightButtonPressEvent')
    native.InvokeEvent('RightButtonReleaseEvent')
    events()


def ui_stroke(widget, point, label, tool='Erase', diameter=2.):
    widget.labelButtons[label].click()
    widget.toolButtons[tool].click()
    widget.brushSize.setValue(diameter)
    events()
    native, _, _ = interactor_at(widget, point)
    for event in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
        native.InvokeEvent(event)
    events()


def export_through_actual_ui(widget):
    """Use the application QAction, modal Export button and completion notice."""
    check('real UI export uses isolated fixed practice results path', Path(widget._practiceConfig['results_root']).resolve() == RESULTS)
    before = set(RESULTS.glob('*.zip')) if RESULTS.exists() else set()
    state = {'seen': False, 'completed': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(25)
    started = time.monotonic()

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 60:
                raise AssertionError('Actual Export dialog timed out.')
            if modal is None:
                return
            if str(modal.objectName) == 'MeniscusExportDialog' and not state['seen']:
                state['seen'] = True
                selected = modal.findChild(qt.QCheckBox, 'MeniscusExportSelectedOnly')
                selected.setChecked(False)
                practice = modal.findChild(qt.QCheckBox, 'MeniscusExportPractice')
                check('real Export modal enforces software-practice scope', practice.checked and not practice.isEnabled())
                box = modal.findChild(qt.QDialogButtonBox, 'MeniscusExportButtons')
                button = box.button(qt.QDialogButtonBox.Ok)
                check('real Export and Cancel modal buttons are visible', button.isVisible() and str(button.text) == 'Export' and box.button(qt.QDialogButtonBox.Cancel).isVisible())
                screenshot = REPORT_DIR / 'private-real-export-dialog.png'
                modal.grab().save(str(screenshot))
                screenshot.chmod(0o600)
                button.click()
            elif str(modal.windowTitle) == 'Export complete':
                state['completed'] = True
                modal.button(qt.QMessageBox.Close).click()
            elif str(modal.objectName) != 'MeniscusExportDialog':
                raise AssertionError('Unexpected modal during real Export UI test.')
        except Exception:
            state['error'] = traceback.format_exc()
            if modal is not None:
                modal.reject()
            timer.stop()

    actions = [action for menu in slicer.util.mainWindow().findChildren(qt.QMenu)
               for action in menu.actions() if str(action.text).startswith('Export results')]
    check('real workspace has one actual Export results menu action', len(actions) == 1)
    timer.connect('timeout()', tick)
    timer.start()
    try:
        actions[0].trigger()
    finally:
        timer.stop()
    check('real Export menu modal and completion notice succeeded', state['seen'] and state['completed'] and state['error'] is None, state['error'])
    events()
    created = set(RESULTS.glob('*.zip')) - before
    check('real Export UI created one versioned software-practice archive', len(created) == 1 and next(iter(created)).name.startswith('SOFTWARE_PRACTICE_ONLY-'))
    REPORT['export_ui_scope'] = 'Actual QAction, modal Export button and completion notice; injected Qt events and fixed isolated practice destination. Native folder picker and human input are not claimed.'
    return next(iter(created))


def run_zhang_workflow():
    REPORT['ui_source_sha256'] = sha256(REPO / 'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO / 'MeniscusAnnotatorLib' / 'core.py')
    REPORT['source_hash_scope'] = CONFIG.get('source_hash_scope')
    count = verify_original()
    check('draw-first scoped original hashes verified before workflow', count > 0)
    copied_hashes = {str(path.relative_to(INPUTS)): sha256(path) for path in INPUTS.rglob('*') if path.is_file()}
    widget, keys = open_widget()
    widget.casesToggle.setChecked(True)
    widget.toolsToggle.setChecked(True)
    approved_arrays = {}
    expectations = {}
    for ordinal, key in enumerate(keys, 1):
        prefix = 'draw-first real case ' + str(ordinal)
        ui_open_case(widget, key, prefix)
        initial = correction_start(widget, prefix + ' initial')
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' exact permitted prediction loaded unchanged', np.array_equal(labels, initial) and not uncertainty.any())
        check(prefix + ' Draw is selected by default with brush controls hidden', widget.editor.activeEffect().name == 'Draw' and widget.toolButtons['Draw'].checked and not widget.brushRow.isVisible())
        display = widget.anatomy.GetDisplayNode()
        check(prefix + ' thin outline default with no fill', not widget.fill.checked and display.GetOpacity2DFill() == 0 and display.GetOpacity2DOutline() == 1 and display.GetSliceIntersectionThickness() == 1)
        check(prefix + ' one bottom Draw instruction and empty canvas text corners', str(widget.instruction.objectName) == 'MeniscusInstruction' and 'Right-click' in str(widget.instruction.text) and not str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperRight) or '') and not str(red().sliceView().cornerAnnotation().GetText(vtk.vtkCornerAnnotation.UpperLeft) or ''))
        for name, colour in [('medial', (.30, .78, .92)), ('lateral', (.95, .64, .31)), ('uncertain', (.76, .56, .88))]:
            check(prefix + ' fixed named colour ' + name, np.allclose(widget.anatomy.GetSegmentation().GetSegment(name).GetColor(), colour))
        k = widget.session.case.n_slices // 2
        i, j = empty_patch(labels, k)
        widget.goSlice(k)
        widget._resetView()
        widget.reviewButton.click()
        widget.goSlice(k)
        events()
        check(prefix + ' explicit software review before drawing', widget.session.state['review'][k]['reviewed'])
        vertices = [(i-22, j-8, k), (i-6, j-8, k), (i-6, j+8, k), (i-22, j+8, k)]
        before = widget.collectArrays()[0].copy()
        before_checkpoint = widget.session.current_checkpoint
        ui_draw_points(widget, vertices, 'medial')
        pending = widget._pendingDraw()
        check(prefix + ' native unfinished contour and bottom guidance visible', pending is not None and pending.rasPoints.GetNumberOfPoints() == 4 and ('Unfinished contour' in str(widget.instruction.text) or 'Finish or discard' in str(widget.instruction.text)) and 'Unsaved contour' in str(widget.saveStatus.text) and widget.finishContourButton.isVisible() and widget.discardContourButton.isVisible())
        check(prefix + ' pending contour has not changed voxels', np.array_equal(widget.collectArrays()[0], before))
        widget.saveButton.click()
        events()
        check(prefix + ' actual Save protects unfinished contour without writing', widget._pendingDraw() is not None and widget.session.current_checkpoint == before_checkpoint and 'Finish or discard' in str(widget.instruction.text))
        export_actions = [action for menu in slicer.util.mainWindow().findChildren(qt.QMenu)
                          for action in menu.actions() if str(action.text).startswith('Export results')]
        check(prefix + ' actual Export action present while drawing', len(export_actions) == 1)
        export_actions[0].trigger()
        events()
        check(prefix + ' actual Export protects unfinished contour without opening a modal', widget._pendingDraw() is not None and qt.QApplication.activeModalWidget() is None and not list(RESULTS.glob('*.zip')))
        ui_close_contour(widget, vertices[-1])
        medial = widget.collectArrays()[0].copy()
        changed = np.argwhere(before != medial)
        check(prefix + ' native right-click commits medial contour only intended acquired slice', widget._pendingDraw() is None and medial[k,j,i-14] == 1 and len(changed) > 0 and set(changed[:,0]) == {k})
        check(prefix + ' committed contour invalidates slice review', not widget.session.state['review'][k]['reviewed'])
        widget.undoButton.click()
        events()
        check(prefix + ' actual Undo restores exact pre-contour prediction', np.array_equal(widget.collectArrays()[0], before))
        widget.redoButton.click()
        events()
        check(prefix + ' actual Redo restores exact medial contour', np.array_equal(widget.collectArrays()[0], medial))
        vertices = [(i+6,j-8,k), (i+22,j-8,k), (i+22,j+8,k), (i+6,j+8,k)]
        ui_draw_points(widget, vertices, 'lateral')
        ui_close_contour(widget, vertices[-1])
        both = widget.collectArrays()[0].copy()
        check(prefix + ' native lateral contour preserves fixed mapping and medial label', both[k,j,i+14] == 2 and both[k,j,i-14] == 1 and set(np.argwhere(both != medial)[:,0]) == {k})
        # Existing predicted voxels, rather than the new fixture contours, are
        # selected for Erase; the original prediction remains immutable.
        for label, value in [('medial',1), ('lateral',2)]:
            positions = np.argwhere(initial == value)
            ek, ej, ei = [int(v) for v in positions[len(positions)//2]]
            widget.goSlice(ek)
            widget._resetView()
            previous = widget.collectArrays()[0].copy()
            ui_stroke(widget, (ei,ej,ek), label)
            erased = widget.collectArrays()[0].copy()
            changed = np.argwhere(previous != erased)
            check(prefix + ' actual Erase control shows brush and removes existing ' + label + ' only intended slice', widget.toolButtons['Erase'].checked and widget.brushRow.isVisible() and erased[ek,ej,ei] == 0 and len(changed) > 0 and set(changed[:,0]) == {ek} and np.all(previous[previous != erased] == value) and np.all(erased[previous != erased] == 0))
            widget.undoButton.click()
            events()
            check(prefix + ' actual Erase Undo exact ' + label, np.array_equal(widget.collectArrays()[0], previous))
            widget.redoButton.click()
            events()
            check(prefix + ' actual Erase Redo exact ' + label, np.array_equal(widget.collectArrays()[0], erased))
        widget.goSlice(k)
        widget._resetView()
        anatomical_before_uncertainty = widget.collectArrays()[0].copy()
        vertices = [(i-18,j-4,k), (i-10,j-4,k), (i-14,j+4,k)]
        ui_draw_points(widget, vertices, 'uncertain')
        ui_close_contour(widget, vertices[-1])
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' native uncertainty contour independent and overlapping', np.array_equal(labels, anatomical_before_uncertainty) and uncertainty[k,j,i-14] == 1 and labels[k,j,i-14] == 1 and set(np.unique(labels)) == {0,1,2})
        check(prefix + ' outstanding uncertainty prevents practice approval', bool(widget.session.approval_errors(labels, uncertainty, practice=True)))
        ui_stroke(widget, (i-14,j,k), 'uncertain', diameter=6.)
        check(prefix + ' actual Erase resolves only uncertainty', not widget.collectArrays()[1].any() and np.array_equal(widget.collectArrays()[0], anatomical_before_uncertainty))
        widget.toolButtons['Draw'].click()
        events()
        check(prefix + ' returning to Draw hides brush and restores guidance', not widget.brushRow.isVisible() and widget.toolButtons['Draw'].checked and 'Click around the boundary. Right-click to close and fill.' in str(widget.instruction.text))
        widget.notesPanel.collapsed = False
        widget.notes.setPlainText('AUTOMATED SOFTWARE QA: Draw-first interface regression. Arbitrary control probes on a permitted prediction; not anatomical assessment, not reader work or research approval.')
        widget.notes.moveCursor(qt.QTextCursor.End)
        widget.notes.setFocus()
        for event_type in (qt.QEvent.KeyPress,qt.QEvent.KeyRelease):
            qt.QApplication.sendEvent(widget.notes,qt.QKeyEvent(event_type,qt.Qt.Key_E,qt.Qt.NoModifier,'e'))
        events()
        check(prefix + ' typing a tool shortcut in notes enters text without changing Draw', str(widget.notes.toPlainText()).endswith('e') and widget.editor.activeEffect().name == 'Draw')
        widget.saveButton.click()
        events()
        saved_labels, saved_uncertainty = widget.collectArrays()
        check(prefix + ' actual Save gives saved feedback', not widget.dirty and 'Saved' in str(widget.saveStatus.text) and widget.session.current_checkpoint is not None)
        verify_saved_case(widget, widget.session.current_checkpoint, saved_labels, saved_uncertainty, prefix + ' saved')
        ui_open_case(widget, keys[ordinal % len(keys)], prefix + ' switch away')
        ui_open_case(widget, key, prefix + ' reopen')
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' case-list switching restores exact annotations and notes', np.array_equal(labels,saved_labels) and np.array_equal(uncertainty,saved_uncertainty) and 'AUTOMATED SOFTWARE QA' in widget.session.state['notes'])
        check(prefix + ' reopened workflow still starts Draw with thin outline', widget.editor.activeEffect().name == 'Draw' and not widget.brushRow.isVisible() and widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0)
        for acquired in range(widget.session.case.n_slices):
            widget.sliceSlider.setValue(acquired+1)
            events()
            check(prefix + ' complete acquired slice ' + str(acquired+1), widget.currentSlice == acquired and abs(plane_index(widget)-acquired) < .001)
            widget.reviewButton.click()
            events()
        widget.caseReviewPanel.collapsed = False
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        labels, uncertainty = widget.collectArrays()
        check(prefix + ' review requirements satisfied for software practice only', not widget.session.approval_errors(labels,uncertainty,practice=True) and bool(widget.session.approval_errors(labels,uncertainty,practice=False)))
        confirm_practice_approval(widget)
        check(prefix + ' approval remains automated and unaccepted research work', widget.session.state['status'] == 'practice_approved' and widget.session.state['approval']['accepted_research_annotation'] is False and widget.session.state['approver'] == 'Software QA (automated)')
        approved_arrays[key] = (labels.copy(), uncertainty.copy())
        expected_file = REPORT_DIR / ('private-zhang-expected-' + str(ordinal) + '.npz')
        np.savez_compressed(expected_file, labels=labels, uncertainty=uncertainty)
        expected_file.chmod(0o600)
        expectations[key] = {'arrays_path':str(expected_file),'notes':widget.session.state['notes'],'review':widget.session.state['review'],'source_identity':widget.session.case.identity}
        widget.goSlice(k)
        widget._resetView()
        slicer.util.mainWindow().resize(1440,900)
        events()
        image = REPORT_DIR / ('private-zhang-real-case-' + str(ordinal) + '.png')
        slicer.util.mainWindow().grab().save(str(image))
        image.chmod(0o600)
    write_private(REPORT_DIR / 'private-zhang-expectations.json', expectations)
    archive_path = export_through_actual_ui(widget)
    check('draw-first UI and core remained fixed during actual workflow', sha256(REPO/'MeniscusAnnotator.py') == REPORT['ui_source_sha256'] and sha256(REPO/'MeniscusAnnotatorLib/core.py') == REPORT['core_source_sha256'])
    finish_workflow(widget, keys, approved_arrays, copied_hashes, count, archive_path=archive_path)


def run_zhang_cold():
    widget, keys = open_widget()
    previous = json.loads((REPORT_DIR/'private-workflow-zhang_workflow.json').read_text())
    check('draw-first cold process follows passed current-source workflow', previous.get('passed') is True and previous['ui_source_sha256'] == sha256(REPO/'MeniscusAnnotator.py') and previous['core_source_sha256'] == sha256(REPO/'MeniscusAnnotatorLib/core.py'))
    REPORT['ui_source_sha256'] = previous['ui_source_sha256']
    REPORT['core_source_sha256'] = previous['core_source_sha256']
    expectations = json.loads((REPORT_DIR/'private-zhang-expectations.json').read_text())
    close_expected = json.loads((REPORT_DIR/'private-resume-expectation.json').read_text())
    input_hashes = {str(path.relative_to(INPUTS)):sha256(path) for path in INPUTS.rglob('*') if path.is_file()}
    for ordinal,key in enumerate(keys,1):
        prefix = 'draw-first cold case ' + str(ordinal)
        ui_open_case(widget,key,prefix)
        expected = expectations[key]
        arrays = np.load(expected['arrays_path'])
        labels,uncertainty = widget.collectArrays()
        check(prefix + ' exact annotations restored after actual process restart', np.array_equal(labels,arrays['labels']) and np.array_equal(uncertainty,arrays['uncertainty']))
        notes = close_expected['notes'] if key == close_expected['case_key'] else expected['notes']
        check(prefix + ' saved notes review and source restored', widget.session.state['notes'] == notes and widget.session.state['review'] == expected['review'] and widget.session.case.identity == expected['source_identity'])
        expected_slice = close_expected['slice_index'] if key == close_expected['case_key'] else widget.session.case.n_slices//2
        check(prefix + ' last displayed acquired slice restored',widget.currentSlice == expected_slice and abs(plane_index(widget)-expected_slice)<.001)
        check(prefix + ' Draw and thin outline defaults restored without contour residue', widget.editor.activeEffect().name == 'Draw' and not widget.brushRow.isVisible() and not widget._pendingDraw() and widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0)
        correction_start(widget,prefix+' provenance')
        verify_saved_case(widget,widget.session.current_checkpoint,labels,uncertainty,prefix)
    check('draw-first cold scoped originals remain unchanged',verify_original()>0)
    check('draw-first cold input-copy bytes remain unchanged',input_hashes == {str(path.relative_to(INPUTS)):sha256(path) for path in INPUTS.rglob('*') if path.is_file()})
    check('draw-first cold UI and core stayed fixed',previous['ui_source_sha256'] == sha256(REPO/'MeniscusAnnotator.py') and previous['core_source_sha256'] == sha256(REPO/'MeniscusAnnotatorLib/core.py'))
    slicer.util.mainWindow().close()
    events()
    check('draw-first cold process closes normally',widget.session is None)


def run_zhang_default_capture():
    """Private visual receipt of untouched starting labels, never QA drawings."""
    REPORT['ui_source_sha256'] = sha256(REPO/'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO/'MeniscusAnnotatorLib/core.py')
    widget,keys = open_widget()
    widget.casesToggle.setChecked(True)
    widget.toolsToggle.setChecked(True)
    ui_open_case(widget,keys[-1],'default real capture')
    initial = correction_start(widget,'default real capture')
    widget.sliceSlider.setValue(widget.session.case.n_slices//2+1)
    widget._resetView()
    events()
    labels,uncertainty = widget.collectArrays()
    check('default real capture contains only untouched permitted prediction',np.array_equal(labels,initial) and not uncertainty.any() and widget.session.current_checkpoint is None and not widget.dirty and not any(row['reviewed'] for row in widget.session.state['review']) and not widget.session.state['notes'])
    check('default real capture displays Draw thin outlines and hidden brush',widget.editor.activeEffect().name == 'Draw' and not widget.brushRow.isVisible() and not widget.fill.checked and widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0 and widget.anatomy.GetDisplayNode().GetSliceIntersectionThickness() == 1)
    slicer.util.mainWindow().resize(1440,900)
    events()
    red().sliceView().forceRender()
    image = REPORT_DIR/'private-zhang-default-real.png'
    slicer.util.mainWindow().grab().save(str(image))
    image.chmod(0o600)
    check('default real capture private image saved',image.is_file() and image.stat().st_size>0)
    folder = widget.session.folder
    slicer.util.mainWindow().close()
    events()
    check('default real capture creates no annotation checkpoints',widget.session is None and not widget.store._checkpoints(folder))
    check('default real capture UI source unchanged',sha256(REPO/'MeniscusAnnotator.py') == REPORT['ui_source_sha256'])


def run_zhang_contour_probe():
    """Record exact native per-click offsets for a reproducible private defect."""
    REPORT['ui_source_sha256'] = sha256(REPO/'MeniscusAnnotator.py')
    widget,keys = open_widget()
    widget.notesPanel.collapsed = False
    widget.caseReviewPanel.collapsed = False
    slicer.util.mainWindow().resize(1440,900)
    ui_open_case(widget,keys[-1],'contour probe')
    k = widget.session.case.n_slices//2
    i,j = empty_patch(widget.collectArrays()[0],k)
    widget.goSlice(k)
    widget._resetView()
    widget.reviewButton.click()
    widget.goSlice(k)
    widget.labelButtons['medial'].click()
    widget.toolButtons['Draw'].click()
    events()
    REPORT['native_probe'] = []
    vertices = [(i-22,j-8,k),(i-6,j-8,k),(i-6,j+8,k),(i-22,j+8,k)]
    native_draw = widget.editor.effectByName('Draw').self()
    require_working = PHASE == 'zhang_contour_recheck'
    initial_arrays = tuple(array.copy() for array in widget.collectArrays())
    for ordinal,point in enumerate(vertices,1):
        native,_,_ = interactor_at(widget,point)
        before = float(red().sliceLogic().GetSliceOffset())
        translation_before = array_matrix(red().mrmlSliceNode().GetSliceToRAS())[:3,3].copy()
        per_event = []
        for event in ('EnterEvent','MouseMoveEvent','LeftButtonPressEvent','LeftButtonReleaseEvent'):
            event_translation = array_matrix(red().mrmlSliceNode().GetSliceToRAS())[:3,3].copy()
            native.InvokeEvent(event)
            per_event.append({'event':event,'translation_before':event_translation.tolist(),'translation_after':array_matrix(red().mrmlSliceNode().GetSliceToRAS())[:3,3].tolist(),'offset_after':float(red().sliceLogic().GetSliceOffset())})
        events()
        pipeline = native_draw.drawPipelines.get(red())
        REPORT['native_probe'].append({'slice_offset_before':before,'slice_offset_after':float(red().sliceLogic().GetSliceOffset()),'active_slice_offset':float(pipeline.activeSliceOffset) if pipeline and pipeline.activeSliceOffset is not None else None,'point_count':pipeline.rasPoints.GetNumberOfPoints() if pipeline else 0,'slice_node_mtime':red().mrmlSliceNode().GetMTime(),'displayed_k':widget.currentSlice,'native_plane_k':plane_index(widget),'translation_before':translation_before.tolist(),'translation_after':array_matrix(red().mrmlSliceNode().GetSliceToRAS())[:3,3].tolist(),'events':per_event})
        if require_working:
            check('real oblique native contour point '+str(ordinal),pipeline is not None and pipeline.rasPoints.GetNumberOfPoints() == ordinal and widget.currentSlice == k and abs(plane_index(widget)-k)<.001)
            ras_before = np.array([pipeline.rasPoints.GetPoint(index) for index in range(ordinal)])
            if ordinal == 1:
                fov = np.array(red().mrmlSliceNode().GetFieldOfView())
                wheel(widget,point,control=1)
                check('real oblique pending contour supports actual Ctrl wheel zoom',not np.allclose(fov[:2],np.array(red().mrmlSliceNode().GetFieldOfView())[:2]) and widget.currentSlice == k)
            elif ordinal == 2:
                position = array_matrix(red().mrmlSliceNode().GetXYToRAS())[:3,3].copy()
                drag(widget,point,'Middle',30,20)
                check('real oblique pending contour supports actual middle drag pan',not np.allclose(position,array_matrix(red().mrmlSliceNode().GetXYToRAS())[:3,3]) and widget.currentSlice == k)
            ras_after = np.array([pipeline.rasPoints.GetPoint(index) for index in range(pipeline.rasPoints.GetNumberOfPoints())])
            check('real oblique native RAS points unchanged by navigation '+str(ordinal),np.array_equal(ras_before,ras_after))
            check('real oblique source annotations unchanged before contour commit '+str(ordinal),all(np.array_equal(a,b) for a,b in zip(initial_arrays,widget.collectArrays())))
    check('contour probe recorded every actual click',len(REPORT['native_probe']) == 4)
    if widget._pendingDraw():
        def discard():
            modal = qt.QApplication.activeModalWidget()
            if modal and str(modal.objectName) == 'MeniscusDiscardContourDialog':
                next(button for button in modal.buttons() if str(button.text) == 'Discard contour').click()
            else:
                qt.QTimer.singleShot(25,discard)
        qt.QTimer.singleShot(0,discard)
        widget.discardContourButton.click()
        events()
    check('contour probe discards uncommitted fixture via actual confirmation',not widget._pendingDraw())
    slicer.util.mainWindow().close()
    events()


def hash_work_tree(root):
    return {str(path.relative_to(root)):sha256(path) for path in Path(root).rglob('*')
            if path.is_file() and path.name != 'case.lock'
            and not any(part.startswith('.pending-') for part in path.parts)}


def run_blank_compatibility():
    REPORT['scope'] = 'READ-ONLY SOFTWARE COMPATIBILITY CHECK on copied human-unverified blank practice work. No drawing, notes, review or approval added; original actor attribution retained.'
    REPORT['ui_source_sha256'] = sha256(REPO/'MeniscusAnnotator.py')
    REPORT['core_source_sha256'] = sha256(REPO/'MeniscusAnnotatorLib/core.py')
    expected = json.loads(Path(CONFIG['compat_expectations']).read_text())
    original_work = Path(expected['original_work_root'])
    check('blank compatibility preserves four existing checkpoints', expected['checkpoint_count'] == 4 and len(expected['checkpoints']) == 4)
    check('blank original work matches its private immutable copy manifest',hash_work_tree(original_work) == expected['original_work_files_sha256'])
    check('blank isolated work initially matches exact copied bytes',hash_work_tree(WORK) == expected['copied_work_files_sha256'])
    input_hashes = {str(p.relative_to(INPUTS)):sha256(p) for p in INPUTS.rglob('*') if p.is_file()}
    dataset = Dataset(INPUTS)
    job = json.loads(JOB_PATH.read_text())
    check('blank compatibility keeps human-unverified actor and explicit blank job',job['practice_context'] == {'purpose':'software_practice','actor':'Preview user (identity unverified)','actor_type':'human_unverified'} and all(rule['annotation_mode']=='blank' for rule in job['cases'].values()))
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    widget.settings = qt.QSettings(str(SETTINGS),qt.QSettings.IniFormat)
    widget.openDataset(str(INPUTS),work_root=str(WORK))
    widget.casesToggle.setChecked(True)
    events()
    groups = {}
    for item in expected['checkpoints']:
        groups.setdefault(item['case_key'],[]).append(item)
    REPORT['saved_cases_reopened'] = len(groups)
    REPORT['saved_checkpoint_count_checked'] = len(expected['checkpoints'])
    for ordinal,(key,items) in enumerate(groups.items(),1):
        prefix = 'blank saved case ' + str(ordinal)
        latest = max(items,key=lambda item:item['checkpoint_relative'])
        state = latest['state']
        ui_open_case(widget,key,prefix)
        expected_path = WORK/latest['checkpoint_relative']
        expected_labels = sitk.GetArrayFromImage(sitk.ReadImage(str(expected_path/'labels.nii.gz')))
        expected_uncertainty = sitk.GetArrayFromImage(sitk.ReadImage(str(expected_path/'uncertainty.nii.gz')))
        labels,uncertainty = widget.collectArrays()
        check(prefix + ' actual new app restores exact latest saved arrays',np.array_equal(labels,expected_labels) and np.array_equal(uncertainty,expected_uncertainty) and widget.session.current_checkpoint == expected_path)
        check(prefix + ' actual new app restores notes review and source identity',str(widget.notes.toPlainText()) == state['notes'] and widget.session.state['review'] == state['review'] and widget.session.state['source_identity'] == state['source_identity'] and widget.session.case.identity == state['source_identity'])
        check(prefix + ' historical blank attribution and approval unchanged',widget.session.state['initialization'] == state['initialization'] and widget.session.state['practice_context'] == state['practice_context'] and widget.session.state['annotator'] == state['annotator'] and widget.session.state['approval'] == state['approval'] and not widget.dirty)
        check(prefix + ' existing work displays with Draw and outline defaults',widget.editor.activeEffect().name == 'Draw' and not widget.fill.checked and widget.anatomy.GetDisplayNode().GetOpacity2DFill() == 0 and not widget.brushRow.isVisible())
        for version,item in enumerate(items,1):
            path = WORK/item['checkpoint_relative']
            saved_state,saved_labels,saved_uncertainty = widget.store._validate_checkpoint(path,widget.session.case)
            check(prefix+' original version metadata '+str(version),saved_state == item['state'])
            verify_saved_case(widget,path,saved_labels,saved_uncertainty,prefix+' preserved version '+str(version))
        widget.closeCase()
    check('blank compatibility created or changed no copied annotation files',hash_work_tree(WORK) == expected['copied_work_files_sha256'])
    check('blank compatibility left original work byte-identical',hash_work_tree(original_work) == expected['original_work_files_sha256'])
    check('blank compatibility input copies unchanged',input_hashes == {str(p.relative_to(INPUTS)):sha256(p) for p in INPUTS.rglob('*') if p.is_file()})
    check('blank compatibility scoped originals unchanged',verify_original()>0)
    check('blank compatibility UI and core stayed fixed',sha256(REPO/'MeniscusAnnotator.py') == REPORT['ui_source_sha256'] and sha256(REPO/'MeniscusAnnotatorLib/core.py') == REPORT['core_source_sha256'])
    slicer.util.mainWindow().close()
    events()
    check('blank compatibility isolated process closes normally',widget.session is None)


def verify_saved_regions(widget, path, regions, regional_uncertainty, prefix):
    """Independent native-grid checks; no anatomical correctness claim."""
    for name, expected in [('regions.nii.gz', regions), ('regional_uncertainty.nii.gz', regional_uncertainty), ('regional_validity.nii.gz', np.zeros_like(regions, dtype=np.uint8))]:
        image = sitk.ReadImage(str(Path(path)/name))
        check(prefix+' exact reopened '+name, np.array_equal(sitk.GetArrayFromImage(image), expected))
        check(prefix+' full native dimensions '+name, image.GetSize() == widget.session.case.shape_xyz)
        independent = nib.load(str(Path(path)/name))
        check(prefix+' native physical grid '+name, np.allclose(independent.affine, widget.session.case.affine_ras, atol=1e-4) and independent.header.get_xyzt_units()[0] == 'mm')
    metadata = json.loads((Path(path)/'regions.json').read_text())
    check(prefix+' pending protocol and honest actor', metadata['protocol']['status'] == 'pending_expert_protocol' and metadata['research_approved'] is False and metadata['annotator'] == 'Software QA (automated)' and metadata['source_identity'] == widget.session.case.identity)
    check(prefix+' explicit unassigned dictionary', metadata['label_mapping']['7'] == 'medial unassigned' and metadata['label_mapping']['8'] == 'lateral unassigned')
    reopened = slicer.util.loadSegmentation(str(Path(path)/'segmentation.seg.nrrd'))
    try:
        from MeniscusAnnotatorLib.regions import REGIONS
        for item in REGIONS:
            actual = slicer.util.arrayFromSegmentBinaryLabelmap(reopened,item['id'],widget.volume)
            check(prefix+' editable regional segment '+item['id'],np.array_equal(actual>0,regions == item['value']))
        actual = slicer.util.arrayFromSegmentBinaryLabelmap(reopened,'regional_uncertain',widget.volume)
        check(prefix+' editable regional uncertainty',np.array_equal(actual>0,regional_uncertainty>0))
    finally:
        helpers=[reopened.GetDisplayNode(),reopened.GetStorageNode()]
        slicer.mrmlScene.RemoveNode(reopened)
        for helper in helpers:
            if helper: slicer.mrmlScene.RemoveNode(helper)


def run_visual_regions():
    """Arbitrary software probes on the same two authorized practice scans."""
    REPORT['ui_source_sha256']=sha256(REPO/'MeniscusAnnotator.py')
    REPORT['core_source_sha256']=sha256(REPO/'MeniscusAnnotatorLib/core.py')
    REPORT['regional_source_sha256']=sha256(REPO/'MeniscusAnnotatorLib/regions.py')
    REPORT['source_hash_scope']=CONFIG.get('source_hash_scope')
    check('regional scoped original hashes verified',verify_original()>0)
    widget,keys=open_widget()
    expected={}
    for ordinal,key in enumerate(keys,1):
        prefix='regional real software case '+str(ordinal)
        ui_open_case(widget,key,prefix)
        widget.taskCombo.setCurrentIndex(0)
        # The close/recovery regression intentionally left one later whole
        # draft after approval. Complete its explicit software-practice approval
        # before testing an independent regional draft; never export that later
        # draft as if its older approval covered it.
        if widget.session.state['status'] != 'practice_approved':
            labels, uncertainty = widget.collectArrays()
            check(prefix+' primary practice setup satisfies existing approval safeguards',not widget.session.approval_errors(labels,uncertainty,practice=True))
            widget.caseReviewPanel.collapsed=False
            confirm_practice_approval(widget)
            check(prefix+' primary practice setup approved through actual control',widget.session.state['status'] == 'practice_approved' and widget.session.state['approval']['accepted_research_annotation'] is False)
        whole,whole_uncertain=widget.collectArrays()
        initial_regions,initial_uncertain=widget.collectRegionalArrays()
        check(prefix+' starts explicitly unassigned',not np.isin(initial_regions,range(1,7)).any() and np.all(initial_regions[whole==1] == 7) and np.all(initial_regions[whole==2] == 8))
        primary_review=json.loads(json.dumps(widget.session.state['review']))
        primary_approval=json.loads(json.dumps(widget.session.state['approval']))
        widget.taskCombo.setCurrentIndex(1)
        events()
        check(prefix+' task shown and regional approval disabled',widget.annotationTask == 'regions' and widget.regionCombo.isVisible() and not widget.approveButton.enabled)
        for parent,value,assigned in [('medial',1,1),('lateral',2,4)]:
            positions=np.argwhere(whole == value)
            k,j,i=[int(v) for v in positions[len(positions)//2]]
            widget.goSlice(k)
            widget.regionCombo.setCurrentIndex(0)
            before,uncertain_before=widget.collectRegionalArrays()
            vertices=[(i-8,j-8,k),(i+8,j-8,k),(i+8,j+8,k),(i-8,j+8,k)]
            ui_draw_points(widget,vertices,parent)
            check(prefix+' unfinished regional Draw retains original target '+parent,widget._pendingDraw() is not None)
            ui_close_contour(widget,vertices[-1])
            regions,_=widget.collectRegionalArrays()
            changed=np.argwhere(regions != before)
            check(prefix+' native region Draw stays inside parent and one acquired slice '+parent,len(changed)>0 and set(changed[:,0]) == {k} and np.all(whole[regions == assigned] == value) and np.any(regions == assigned))
            check(prefix+' regional Draw preserves both whole masks '+parent,np.array_equal(widget.collectArrays()[0],whole))
            widget.undoButton.click();events()
            check(prefix+' regional Draw Undo exact '+parent,np.array_equal(widget.collectRegionalArrays()[0],before))
            widget.redoButton.click();events()
            check(prefix+' regional Draw Redo exact '+parent,np.array_equal(widget.collectRegionalArrays()[0],regions))
            point=np.argwhere(regions[k] == assigned)[len(np.argwhere(regions[k] == assigned))//2]
            pj,pi=[int(v) for v in point]
            widget.regionCombo.setCurrentIndex(1)
            ui_stroke(widget,(pi,pj,k),parent,tool='Paint',diameter=3.)
            body,_=widget.collectRegionalArrays()
            check(prefix+' actual Paint changes region without changing parent '+parent,np.any(body == assigned+1) and np.array_equal(widget.collectArrays()[0],whole))
            ui_stroke(widget,(pi,pj,k),parent,tool='Erase',diameter=3.)
            erased,_=widget.collectRegionalArrays()
            check(prefix+' regional Erase returns tissue to unassigned '+parent,np.any((body == assigned+1) & (erased == (7 if value==1 else 8))) and np.array_equal(widget.collectArrays()[0],whole))
            widget.undoButton.click();events()
            check(prefix+' regional Erase Undo exact '+parent,np.array_equal(widget.collectRegionalArrays()[0],body))
            widget.redoButton.click();events()
            check(prefix+' regional Erase Redo exact '+parent,np.array_equal(widget.collectRegionalArrays()[0],erased))
            widget.boundaryUncertainButton.click()
            ui_stroke(widget,(pi,pj,k),parent,tool='Paint',diameter=2.)
            check(prefix+' boundary uncertainty is independent '+parent,widget.collectRegionalArrays()[1].any() and np.array_equal(widget.collectArrays()[0],whole) and np.array_equal(widget.collectArrays()[1],whole_uncertain))
            widget.boundaryUncertainButton.click()
            widget.regionCombo.setCurrentIndex(2)
            widget.regionalAssessmentPanel.collapsed=False
            widget.regionStatusCombo.setCurrentIndex(2)
            events()
            check(prefix+' absent posterior region allowed without tissue '+parent,widget.regionalState['assessments'][parent+'_posterior']['status'] == 'absent' and not np.any(widget.collectRegionalArrays()[0] == assigned+2))
        widget.regionNotes.setPlainText('AUTOMATED SOFTWARE QA only: arbitrary regional control probe, not expert boundaries.')
        widget.regionNotes.moveCursor(qt.QTextCursor.End)
        widget.regionNotes.setFocus()
        active=widget.editor.activeEffect().name
        for kind in (qt.QEvent.KeyPress,qt.QEvent.KeyRelease):
            qt.QApplication.sendEvent(widget.regionNotes,qt.QKeyEvent(kind,qt.Qt.Key_D,qt.Qt.NoModifier,'d'))
        events()
        check(prefix+' region notes do not trigger Draw shortcut',str(widget.regionNotes.toPlainText()).endswith('d') and widget.editor.activeEffect().name == active)
        check(prefix+' whole review and approval remain independent',widget.session.state['review'] == primary_review and widget.session.state['approval'] == primary_approval)
        widget.saveButton.click();events()
        check(prefix+' actual Save includes regions without claiming regional approval',not widget.dirty and widget.session.state['status'] == 'practice_approved' and widget.session.state['approval'] == primary_approval and widget.regionalState['research_approved'] is False)
        regions,uncertain=widget.collectRegionalArrays()
        verify_saved_regions(widget,widget.session.current_checkpoint,regions,uncertain,prefix)
        arrays=REPORT_DIR/('private-regions-expected-'+str(ordinal)+'.npz')
        np.savez_compressed(arrays,whole=whole,whole_uncertainty=whole_uncertain,regions=regions,regional_uncertainty=uncertain)
        arrays.chmod(0o600)
        expected[key]={'arrays_path':str(arrays),'regional_state':widget.regionalState,'whole_review':primary_review,'whole_approval':primary_approval,'slice_index':widget.currentSlice,'region':widget.activeRegion,'compartment':widget._parentCompartment()}
        image=REPORT_DIR/('private-regional-real-'+str(ordinal)+'.png')
        slicer.util.mainWindow().grab().save(str(image));image.chmod(0o600)
    write_private(REPORT_DIR/'private-regional-expectations.json',expected)
    archive=export_through_actual_ui(widget)
    with zipfile.ZipFile(archive) as z:
        for key,item in expected.items():
            folder='cases/'+hashlib.sha256(key.encode()).hexdigest()[:24]+'/'
            metadata=json.loads(z.read(folder+'regions.json'))
            check('regional exported draft metadata remains pending '+str(keys.index(key)+1),metadata['research_approved'] is False and metadata['protocol']['status'] == 'pending_expert_protocol')
            for filename,field in [('regions.nii.gz','regions'),('regional_uncertainty.nii.gz','regional_uncertainty'),('regional_validity.nii.gz',None)]:
                temp=REPORT_DIR/('private-export-regional-'+str(keys.index(key))+'-'+filename)
                temp.write_bytes(z.read(folder+filename));temp.chmod(0o600)
                image=sitk.ReadImage(str(temp));array=sitk.GetArrayFromImage(image)
                arrays=np.load(item['arrays_path'])
                check('regional export exact grid and voxels '+str(keys.index(key))+' '+filename,image.GetSize() == widget.dataset.by_key[key].shape_xyz and np.array_equal(array,arrays[field] if field else np.zeros_like(arrays['regions'])))
                temp.unlink()
    check('regional original input files remain unchanged',verify_original()>0)
    widget.closeCase()
    events()


def run_visual_regions_cold():
    widget,keys=open_widget()
    expected=json.loads((REPORT_DIR/'private-regional-expectations.json').read_text())
    prior=json.loads((REPORT_DIR/'private-workflow-visual_regions.json').read_text())
    check('regional cold follows passed same application',prior['passed'] and prior['ui_source_sha256'] == sha256(REPO/'MeniscusAnnotator.py') and prior['regional_source_sha256'] == sha256(REPO/'MeniscusAnnotatorLib/regions.py'))
    for ordinal,key in enumerate(keys,1):
        prefix='regional cold real case '+str(ordinal)
        ui_open_case(widget,key,prefix)
        item=expected[key];arrays=np.load(item['arrays_path'])
        whole,whole_uncertain=widget.collectArrays();regions,uncertain=widget.collectRegionalArrays()
        check(prefix+' exact whole and regional arrays after process restart',all(np.array_equal(a,b) for a,b in [(whole,arrays['whole']),(whole_uncertain,arrays['whole_uncertainty']),(regions,arrays['regions']),(uncertain,arrays['regional_uncertainty'])]))
        check(prefix+' whole review/approval and regional metadata preserved',widget.session.state['review'] == item['whole_review'] and widget.session.state['approval'] == item['whole_approval'] and widget.regionalState == item['regional_state'])
        check(prefix+' task compartment region and slice restored',widget.annotationTask == 'regions' and widget._parentCompartment() == item['compartment'] and widget.activeRegion == item['region'] and widget.currentSlice == item['slice_index'])
        verify_saved_regions(widget,widget.session.current_checkpoint,regions,uncertain,prefix)
    check('regional cold original input files unchanged',verify_original()>0)
    widget.closeCase();events()


try:
    if PHASE == 'workflow':
        run_workflow()
    elif PHASE == 'correction_workflow':
        run_correction_workflow()
    elif PHASE == 'finish':
        run_finish()
    elif PHASE == 'resume':
        run_resume()
    elif PHASE == 'correction_cold_all':
        run_correction_cold_all()
    elif PHASE == 'orientation_recheck':
        run_orientation_recheck()
    elif PHASE == 'status_recheck':
        run_status_recheck()
    elif PHASE == 'zhang_workflow':
        run_zhang_workflow()
    elif PHASE == 'zhang_cold':
        run_zhang_cold()
    elif PHASE == 'zhang_default_capture':
        run_zhang_default_capture()
    elif PHASE == 'zhang_contour_probe':
        run_zhang_contour_probe()
    elif PHASE == 'zhang_contour_recheck':
        run_zhang_contour_probe()
    elif PHASE == 'visual_regions':
        run_visual_regions()
    elif PHASE == 'visual_regions_cold':
        run_visual_regions_cold()
    elif PHASE == 'blank_compatibility':
        run_blank_compatibility()
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
