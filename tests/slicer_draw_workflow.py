"""Actual-desktop Draw/geometry matrix using procedural synthetic inputs only.

Run in pinned Slicer with MENISCUS_DRAW_OUTPUT outside the repository. Phases:
workflow (fresh directory), resume (same successful output), layout (same output).
The import-safe run_phase(exit_application=False) also supports the installed
maintainer TestKit. Reports distinguish injected Qt/VTK events from human tests.
"""
import datetime
import inspect
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

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
# In an installed TestKit, the application must already be available through
# its installed module path. No second application implementation is imported.
if (TEST_DIR.parent / 'MeniscusAnnotatorLib').is_dir():
    sys.path.insert(0, str(TEST_DIR.parent))
from draw_fixture import make_draw_matrix
from MeniscusAnnotatorLib.core import Dataset, sha256

OUTPUT = Path(os.environ['MENISCUS_DRAW_OUTPUT']).resolve()
PHASE = os.environ.get('MENISCUS_DRAW_PHASE', 'workflow')
SCALE_NAME = os.environ.get('MENISCUS_DRAW_SCALE_NAME', '100')
REPORT = {}
WIDGET = None


def events():
    slicer.app.processEvents()


def check(name, value, detail=None):
    item = {'name': name, 'passed': bool(value)}
    if detail is not None:
        item['detail'] = detail
    REPORT['checks'].append(item)
    (OUTPUT / ('draw-progress-' + PHASE + '.json')).write_text(json.dumps(
        {'checks': len(REPORT['checks']), 'last_check': item}, indent=2) + '\n')
    if not value:
        raise AssertionError(name)


def matrix(node_matrix):
    return np.array([[node_matrix.GetElement(r, c) for c in range(4)] for r in range(4)])


def red():
    return slicer.app.layoutManager().sliceWidget('Red')


def plane_k(widget):
    return float((np.linalg.inv(widget.session.case.affine_ras)
                  @ matrix(red().mrmlSliceNode().GetSliceToRAS())[:, 3])[2])


def arrays(widget):
    values = widget.collectArrays()
    return tuple(value.copy() for value in values)


def same(actual, expected):
    return all(np.array_equal(a, b) for a, b in zip(actual, expected))


def button(text):
    matches = [b for kind in (qt.QPushButton, qt.QToolButton)
               for b in slicer.util.mainWindow().findChildren(kind)
               if str(b.text).replace('&', '') == text and b.isVisible()]
    if len(matches) != 1:
        raise AssertionError('Expected one visible control: ' + text)
    return matches[0]


def key(target, key_code, text='', modifiers=qt.Qt.NoModifier):
    target.setFocus()
    events()
    for kind in (qt.QEvent.KeyPress, qt.QEvent.KeyRelease):
        qt.QApplication.sendEvent(target, qt.QKeyEvent(kind, key_code, modifiers, text))
    events()


def xy_for_ijk(widget, ijk):
    point = widget.session.case.affine_ras @ np.array([*ijk, 1.])
    inverse = np.linalg.inv(matrix(red().mrmlSliceNode().GetXYToRAS()))
    return tuple(int(round(v)) for v in (inverse @ point)[:2])


def interactor(widget, point, control=0):
    x, y = xy_for_ijk(widget, point)
    result = red().sliceView().interactorStyle().GetInteractor()
    result.SetEventInformation(x, y, control, 0)
    return result


def pending_points(widget):
    native = widget.editor.effectByName('Draw').self()
    return sum(p.rasPoints.GetNumberOfPoints() for p in native.drawPipelines.values())


def points(widget, vertices, label='medial'):
    if widget.activeLabel != label:
        widget.labelButtons[label].click()
        events()
    if not widget.editor.activeEffect() or widget.editor.activeEffect().name != 'Draw':
        widget.toolButtons['Draw'].click()
        events()
    clicks = []
    for point in vertices:
        xy = xy_for_ijk(widget, point)
        xy_to_ras = matrix(red().mrmlSliceNode().GetXYToRAS())
        clicked_ras = (xy_to_ras @ [xy[0], xy[1], 0, 1])[:3]
        # Native pointer events have integer pixel coordinates. The intended
        # voxel center may therefore differ by at most half a pixel on each
        # in-plane axis; this does not change the source/export voxel grid.
        clicks.append({'clicked_ras': clicked_ras.tolist(),
                       'pixel_error_bound_mm': float(.5 * (np.linalg.norm(xy_to_ras[:3, 0])
                                                           + np.linalg.norm(xy_to_ras[:3, 1])) + 1e-4)})
        native = interactor(widget, point)
        for name in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
            native.InvokeEvent(name)
        events()
    return clicks


def right_click(widget, point):
    native = interactor(widget, point)
    native.InvokeEvent('RightButtonPressEvent')
    native.InvokeEvent('RightButtonReleaseEvent')
    events()


def draw(widget, vertices, label='medial'):
    points(widget, vertices, label)
    right_click(widget, vertices[-1])


def stroke(widget, point, label='medial', tool='Erase', diameter=1.):
    widget.labelButtons[label].click()
    widget.toolButtons[tool].click()
    widget.brushSize.setValue(diameter)
    events()
    native = interactor(widget, point)
    for name in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
        native.InvokeEvent(name)
    events()


def wheel(widget, point, control=0, backwards=False):
    native = interactor(widget, point, control)
    native.InvokeEvent('MouseWheelBackwardEvent' if backwards else 'MouseWheelForwardEvent')
    events()


def right_drag(widget, point):
    native = interactor(widget, point)
    start = native.GetEventPosition()
    native.InvokeEvent('RightButtonPressEvent')
    native.SetEventInformation(start[0] + 22, start[1] + 16, 0, 0)
    native.InvokeEvent('MouseMoveEvent')
    native.InvokeEvent('RightButtonReleaseEvent')
    events()


def middle_pan(widget, point):
    native = interactor(widget, point)
    start = native.GetEventPosition()
    native.InvokeEvent('MiddleButtonPressEvent')
    native.SetEventInformation(start[0] + 19, start[1] - 11, 0, 0)
    native.InvokeEvent('MouseMoveEvent')
    native.InvokeEvent('MiddleButtonReleaseEvent')
    events()


def instruction(widget):
    label = getattr(widget, 'instruction', None)
    check('one contextual instruction control exists', label is not None
          and str(label.objectName) == 'MeniscusInstruction')
    return str(label.text)


def discard(widget, confirm):
    state = {'seen': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(20)
    started = time.monotonic()

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 10:
                raise AssertionError('Discard contour confirmation timed out.')
            if modal is None:
                return
            if str(modal.objectName) != 'MeniscusDiscardContourDialog':
                raise AssertionError('Unexpected discard modal: ' + str(modal.objectName))
            choices = {str(b.text).replace('&', ''): b for b in modal.buttons()}
            check('discard defaults to preserving the unfinished contour',
                  modal.defaultButton() == choices['Keep drawing'])
            state['seen'] = True
            choices['Discard contour' if confirm else 'Keep drawing'].click()
        except Exception:
            state['error'] = traceback.format_exc()
            if modal:
                modal.reject()
            timer.stop()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        widget.discardContourButton.click()
    finally:
        timer.stop()
    check('explicit discard confirmation was displayed', state['seen'], state['error'])
    if state['error']:
        raise AssertionError(state['error'])
    events()


def approve(widget):
    widget.caseReviewPanel.collapsed = False
    events()
    scroll = widget.rightDock.findChild(qt.QScrollArea)
    if scroll is not None:
        scroll.ensureWidgetVisible(widget.approveButton)
    events()
    check('whole approval remains reachable inside expanded case details',
          widget.approveButton.isVisible()
          and widget.approveButton.visibleRegion().boundingRect().contains(widget.approveButton.rect))
    state = {'seen': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(20)
    started = time.monotonic()

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if modal is not None:
                if str(modal.windowTitle) != 'Approve case':
                    raise AssertionError('Unexpected practice approval dialog: ' + str(modal.windowTitle))
                check('approval names software-only actor', 'Software QA (automated)' in str(modal.text))
                state['seen'] = True
                modal.button(qt.QMessageBox.Yes).click()
            elif time.monotonic() - started > 10:
                raise AssertionError('Practice approval dialog timed out.')
        except Exception:
            state['error'] = traceback.format_exc()
            if modal is not None:
                modal.reject()
            timer.stop()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        widget.approveButton.click()
    finally:
        timer.stop()
    check('actual practice approval control confirmed explicitly', state['seen'] and not state['error'], state['error'])
    events()


def export_via_ui(widget):
    """Trigger the real menu action and actual modal controls; no export helper."""
    prior = widget._practiceConfig
    target = OUTPUT / 'Exports'
    widget._practiceConfig = dict(prior or {}, results_root=str(target))
    state = {'seen': False, 'completed': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(25)
    started = time.monotonic()

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 30:
                raise AssertionError('Export dialog timed out.')
            if modal is None:
                return
            if str(modal.objectName) == 'MeniscusExportDialog' and not state['seen']:
                state['seen'] = True
                checkbox = modal.findChild(qt.QCheckBox, 'MeniscusExportSelectedOnly')
                checkbox.setChecked(False)
                box = modal.findChild(qt.QDialogButtonBox, 'MeniscusExportButtons')
                export_button = box.button(qt.QDialogButtonBox.Ok)
                check('actual Export and Cancel controls are visible', export_button.isVisible()
                      and box.button(qt.QDialogButtonBox.Cancel).isVisible())
                modal.grab().save(str(OUTPUT / 'synthetic-draw-export-dialog.png'))
                export_button.click()
            elif str(modal.windowTitle) == 'Export complete':
                state['completed'] = True
                modal.button(qt.QMessageBox.Close).click()
            elif str(modal.objectName) != 'MeniscusExportDialog':
                raise AssertionError('Unexpected export modal: ' + str(modal.windowTitle))
        except Exception:
            state['error'] = traceback.format_exc()
            timer.stop()
            if modal:
                modal.reject()

    actions = [action for menu in slicer.util.mainWindow().findChildren(qt.QMenu)
               for action in menu.actions() if str(action.text).startswith('Export results')]
    check('workspace has one actual Export results action', len(actions) == 1)
    timer.connect('timeout()', tick)
    timer.start()
    try:
        actions[0].trigger()
    finally:
        timer.stop()
        widget._practiceConfig = prior
    check('actual Export menu and modal completed', state['seen'] and state['completed']
          and not state['error'], state['error'])
    archives = list(target.glob('*.zip'))
    check('one versioned software-practice ZIP created', len(archives) == 1
          and archives[0].name.startswith('SOFTWARE_PRACTICE_ONLY-'))
    REPORT['export_ui_scope'] = ('QAction and real modal Export button, injected Qt events; '
                                 'fixed synthetic destination, native folder picker not tested')
    return archives[0]


def open_case_ui(widget, key_value):
    rows = [row for row in range(widget.caseTable.rowCount)
            if widget.caseTable.item(row, 0).data(qt.Qt.UserRole) == key_value]
    check('requested synthetic source case appears in case list', len(rows) == 1)
    widget.caseTable.setCurrentCell(rows[0], 0)
    widget.caseTable.selectRow(rows[0])
    widget.openCaseButton.click()
    events()
    check('case-list Open control opened requested identity', widget.session
          and widget.session.case.key == key_value)


def open_widget(source, work, force_docks=True):
    global WIDGET
    slicer.util.selectModule('MeniscusAnnotator')
    WIDGET = slicer.modules.meniscusannotator.widgetRepresentation().self()
    settings = OUTPUT / 'Settings' / 'workspace.ini'
    settings.parent.mkdir(parents=True, exist_ok=True)
    WIDGET.settings = qt.QSettings(str(settings), qt.QSettings.IniFormat)
    WIDGET.openDataset(str(source), work_root=str(work))
    if force_docks:
        WIDGET.casesToggle.setChecked(True)
        WIDGET.toolsToggle.setChecked(True)
    events()
    app_source = Path(inspect.getsourcefile(WIDGET.__class__)).resolve()
    REPORT['application_source_path'] = str(app_source)
    REPORT['application_source_sha256'] = sha256(app_source)
    core_source = Path(inspect.getsourcefile(Dataset)).resolve()
    REPORT['core_source_path'] = str(core_source)
    REPORT['core_source_sha256'] = sha256(core_source)
    loaded = getattr(inspect.getmodule(WIDGET.__class__), 'SOURCE_IDENTITY', {})
    REPORT['loaded_source_identity'] = loaded
    initialized = loaded.get('application_files_sha256', {})
    check('loaded application matches files at module initialization',
          initialized.get('MeniscusAnnotator.py') == REPORT['application_source_sha256']
          and initialized.get('MeniscusAnnotatorLib/core.py') == REPORT['core_source_sha256'])
    REPORT['app_source_is_outside_testkit'] = app_source.parent != TEST_DIR
    return WIDGET


def verify_geometry(widget, key_value, item):
    affine = widget.session.case.affine_ras
    actual = vtk.vtkMatrix4x4()
    widget.volume.GetIJKToRASMatrix(actual)
    check(key_value + ' source grid retained in live Slicer',
          widget.volume.GetImageData().GetDimensions() == tuple(item['shape_xyz'])
          and np.allclose(matrix(actual), item['affine_ras'], atol=1e-4))
    side = 'Left knee' if item['side'] == 'L' else 'Right knee'
    check(key_value + ' case identity and physical side prominent and explicit',
          side in str(widget.identityLabel.text)
          and item['participant_id'] in str(widget.identityLabel.text)
          and 'M000' in str(widget.identityLabel.text))
    check(key_value + ' fixed medial/lateral values on known physical landmarks',
          all(widget.collectArrays()[0][tuple(reversed(item[role + '_seed_ijk']))] == value
              for role, value in [('medial', 1), ('lateral', 2)]))
    permitted = np.asarray(nib.load(str(widget.session.case.folder / 'starting_mask.nii.gz')).dataobj).transpose(2, 1, 0)
    check(key_value + ' initial complete masks match supplied native labels exactly',
          np.array_equal(widget.collectArrays()[0], permitted) and not widget.collectArrays()[1].any())
    check(key_value + ' complete named compartments and separate uncertainty only',
          set(widget.labelButtons) == {'medial', 'lateral', 'uncertain'}
          and widget.anatomy.GetSegmentation().GetSegment('medial').GetName() == 'Medial meniscus'
          and widget.anatomy.GetSegmentation().GetSegment('lateral').GetName() == 'Lateral meniscus')
    for segment, color in [('medial', (.30, .78, .92)),
                           ('lateral', (.95, .64, .31)), ('uncertain', (.76, .56, .88))]:
        check(key_value + ' established compartment color ' + segment,
              np.allclose(widget.anatomy.GetSegmentation().GetSegment(segment).GetColor(), color))
    for role in ('medial', 'lateral'):
        physical = (affine @ [*item[role + '_seed_ijk'], 1])[:3]
        check(key_value + ' ' + role + ' physical coordinate independent of side/direction',
              np.allclose(physical, item[role + '_seed_ras_mm'], atol=1e-4))
    normal = affine[:3, 2] / np.linalg.norm(affine[:3, 2])
    up = affine[:3, 1] / np.linalg.norm(affine[:3, 1])
    if up[2] < 0:
        up = -up
    horizontal = np.cross(up, normal)
    annotation = red().sliceView().cornerAnnotation()
    for edge, vector in [(vtk.vtkCornerAnnotation.LeftEdge, -horizontal),
                         (vtk.vtkCornerAnnotation.RightEdge, horizontal),
                         (vtk.vtkCornerAnnotation.UpperEdge, up),
                         (vtk.vtkCornerAnnotation.LowerEdge, -up)]:
        axis = int(np.argmax(np.abs(vector)))
        dominant = ('R', 'A', 'S')[axis] if vector[axis] > 0 else ('L', 'P', 'I')[axis]
        actual_label = annotation.GetText(edge)
        check(key_value + ' geometry-derived direction marker ' + str(edge),
              actual_label.startswith(dominant), {'physical_vector': vector.tolist(), 'marker': actual_label})
    for acquired in range(widget.session.case.n_slices):
        widget.sliceSlider.setValue(acquired + 1)
        events()
        readout = [int(n) for n in re.findall(r'\d+', str(widget.sliceReadout.text))]
        check(key_value + ' acquired slice ' + str(acquired + 1),
              widget.currentSlice == acquired and abs(plane_k(widget) - acquired) < .001
              and readout[:2] == [acquired + 1, widget.session.case.n_slices])
    key(widget.sliceSlider, qt.Qt.Key_Home)
    check(key_value + ' Home reaches first acquired plane', widget.currentSlice == 0
          and abs(plane_k(widget)) < .001)
    key(widget.sliceSlider, qt.Qt.Key_End)
    check(key_value + ' End reaches last acquired plane',
          widget.currentSlice == widget.session.case.n_slices - 1
          and abs(plane_k(widget) - widget.currentSlice) < .001)
    middle = widget.session.case.n_slices // 2
    widget.goSlice(middle)
    wheel(widget, (48, 38, middle))
    check(key_value + ' wheel forward steps one source acquired index',
          widget.currentSlice == middle + 1 and abs(plane_k(widget) - middle - 1) < .001)
    wheel(widget, (48, 38, middle + 1), backwards=True)
    check(key_value + ' wheel backward restores source index in either physical direction',
          widget.currentSlice == middle and abs(plane_k(widget) - middle) < .001)
    widget.previousButton.click()
    events()
    check(key_value + ' Previous button steps one acquired index', widget.currentSlice == middle - 1)
    widget.nextButton.click()
    events()
    check(key_value + ' Next button restores acquired index', widget.currentSlice == middle)


def verify_saved(widget, checkpoint, expected, prefix):
    metadata = widget.session.case.metadata
    for name, value in [('labels.nii.gz', expected[0]), ('uncertainty.nii.gz', expected[1]),
                        ('validity.nii.gz', np.zeros_like(expected[0], dtype=np.uint8))]:
        image = nib.load(str(checkpoint / name))
        check(prefix + ' independent nibabel values ' + name,
              np.array_equal(np.asarray(image.dataobj).transpose(2, 1, 0), value))
        check(prefix + ' complete native physical grid ' + name,
              image.shape == widget.session.case.shape_xyz
              and np.allclose(image.affine, widget.session.case.affine_ras, atol=1e-4)
              and image.header.get_xyzt_units()[0] == 'mm')
        independent = sitk.ReadImage(str(checkpoint / name))
        check(prefix + ' SimpleITK values and LPS geometry ' + name,
              np.array_equal(sitk.GetArrayFromImage(independent), value)
              and np.allclose(independent.GetSpacing(), metadata['spacing_xyz_mm'], atol=1e-5)
              and np.allclose(independent.GetOrigin(), metadata['origin_lps_mm'], atol=1e-4)
              and np.allclose(np.array(independent.GetDirection()).reshape(3, 3),
                              metadata['direction_lps_columns'], atol=1e-5))
    reopened = slicer.util.loadSegmentation(str(checkpoint / 'segmentation.seg.nrrd'))
    check(prefix + ' editable Slicer segmentation reopens', reopened is not None)
    if reopened:
        try:
            for segment, value in [('medial', expected[0] == 1),
                                   ('lateral', expected[0] == 2), ('uncertain', expected[1] != 0)]:
                actual = slicer.util.arrayFromSegmentBinaryLabelmap(reopened, segment, widget.volume)
                check(prefix + ' editable fixed segment ' + segment, np.array_equal(actual != 0, value))
        finally:
            helpers = [reopened.GetDisplayNode(), reopened.GetStorageNode()]
            slicer.mrmlScene.RemoveNode(reopened)
            for node in helpers:
                if node:
                    slicer.mrmlScene.RemoveNode(node)
    state = json.loads((checkpoint / 'annotation.json').read_text())
    check(prefix + ' software attribution and validity remain separate from research',
          state['annotator'] == 'Software QA (automated)'
          and state['annotation_purpose'] == 'software_practice')


def transformed_source_guard(widget, vertices, before):
    """Unsupported live source geometry must abort before native rasterization."""
    state = {'seen': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(10)
    transform = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLinearTransformNode',
                                                 'SYNTHETIC unsupported source-transform test')

    def tick():
        modal = qt.QApplication.activeModalWidget()
        if modal is None:
            return
        try:
            if str(modal.windowTitle) != 'Editing blocked':
                raise AssertionError('Unexpected transformed-source dialog: ' + str(modal.windowTitle))
            state['seen'] = True
            check('unsupported source geometry gives a recovery action without stack trace',
                  any(action in str(modal.text) for action in ('Reopen', 'Restore'))
                  and 'Traceback' not in str(modal.text), str(modal.text))
            modal.accept()
        except Exception:
            state['error'] = traceback.format_exc()
            modal.reject()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        widget.volume.SetAndObserveTransformNodeID(transform.GetID())
        events()
        right_click(widget, vertices[-1])
        deadline = time.monotonic() + 2
        while not state['seen'] and not state['error'] and time.monotonic() < deadline:
            events()
            time.sleep(.01)
    finally:
        widget.volume.SetAndObserveTransformNodeID(None)
        slicer.mrmlScene.RemoveNode(transform)
        timer.stop()
    check('unsupported transformed source blocks Draw without losing contour',
          state['seen'] and not state['error'] and pending_points(widget) == 3
          and same(arrays(widget), before), state['error'])


def stable_contour_view_updates(widget, key_value):
    """Real oblique regression: same-plane view updates must accept next point.

    The pinned native Draw implementation compares its active offset exactly.
    Therefore verified same-plane updates must not introduce tiny resnapping
    drift or silently reject subsequent native vertices. RAS points stay intact.
    """
    k = widget.session.case.n_slices // 2
    widget.goSlice(k)
    widget._resetView()
    before = arrays(widget)
    vertices = [(43, 33, k), (53, 33, k), (53, 43, k), (43, 43, k)]

    def native_ras():
        return [tuple(p.rasPoints.GetPoint(index))
                for p in widget.editor.effectByName('Draw').self().drawPipelines.values()
                for index in range(p.rasPoints.GetNumberOfPoints())]

    clicks = points(widget, vertices[:1])
    old_points = native_ras()
    old_offset = red().sliceLogic().GetSliceOffset()
    for _ in range(12):
        red().mrmlSliceNode().Modified()
        events()
    check(key_value + ' repeated same-plane Modified preserves exact native offset and point',
          pending_points(widget) == 1 and native_ras() == old_points
          and red().sliceLogic().GetSliceOffset() == old_offset)
    wheel(widget, vertices[0], control=1)
    check(key_value + ' zoom does not move existing native contour point', native_ras() == old_points)
    clicks.extend(points(widget, vertices[1:2]))
    check(key_value + ' native second point accepted after zoom', pending_points(widget) == 2)
    old_points = native_ras()
    old_view = matrix(red().mrmlSliceNode().GetXYToRAS())
    middle_pan(widget, (48, 38, k))
    check(key_value + ' actual middle pan preserves previous native RAS points',
          native_ras() == old_points and not np.array_equal(old_view, matrix(red().mrmlSliceNode().GetXYToRAS()))
          and abs(plane_k(widget) - k) < .001)
    clicks.extend(points(widget, vertices[2:3]))
    check(key_value + ' native third point accepted after pan', pending_points(widget) == 3)
    old_points = native_ras()
    old_offset = red().sliceLogic().GetSliceOffset()
    widget.goSlice(k)
    events()
    check(key_value + ' same-index goSlice does not reproject unfinished contour',
          native_ras() == old_points and red().sliceLogic().GetSliceOffset() == old_offset)
    clicks.extend(points(widget, vertices[3:]))
    check(key_value + ' fourth point accepted after same-plane navigation', pending_points(widget) == 4)
    actual_ras = np.asarray(native_ras())
    expected_ras = np.asarray([click['clicked_ras'] for click in clicks])
    intended_centers = np.asarray([(widget.session.case.affine_ras @ [*point, 1])[:3] for point in vertices])
    quantization_errors = np.linalg.norm(expected_ras - intended_centers, axis=1)
    bounds = np.asarray([click['pixel_error_bound_mm'] for click in clicks])
    check(key_value + ' all contour vertices retain intended physical coordinates',
          np.allclose(actual_ras, expected_ras, atol=1e-4, rtol=0)
          and np.all(quantization_errors <= bounds)
          and same(arrays(widget), before))
    right_click(widget, vertices[-1])
    filled = arrays(widget)
    differences = np.argwhere(filled[0] != before[0])
    check(key_value + ' view-adjusted contour fills original acquired slice only',
          pending_points(widget) == 0 and filled[0][k, 38, 48] == 1
          and len(differences) > 0 and set(differences[:, 0]) == {k})
    button('Undo').click()
    events()
    check(key_value + ' view-adjusted contour Undo exact', same(arrays(widget), before))


def contour_guards(widget, key_value, other_key, check_exit=False):
    k = widget.session.case.n_slices // 2
    widget.goSlice(k)
    widget._resetView()
    widget.labelButtons['medial'].click()
    widget.toolButtons['Draw'].click()
    vertices = [(10, 60, k), (18, 60, k), (14, 68, k)]
    before = arrays(widget)
    points(widget, vertices[:1])
    check(key_value + ' one uncommitted point remains distinct from mask',
          pending_points(widget) == 1 and same(arrays(widget), before))
    check(key_value + ' one point cannot be filled', not widget.finishContourButton.enabled)
    right_click(widget, vertices[0])
    check(key_value + ' right click never silently loses one point',
          pending_points(widget) == 1 and same(arrays(widget), before))
    discard(widget, False)
    check(key_value + ' Keep drawing preserves one point', pending_points(widget) == 1)
    discard(widget, True)
    check(key_value + ' explicit discard removes only unfinished point',
          pending_points(widget) == 0 and same(arrays(widget), before))
    points(widget, vertices)
    check(key_value + ' unfinished contour not committed',
          pending_points(widget) == 3 and same(arrays(widget), before))
    check(key_value + ' unfinished contour is visibly unsaved',
          'Unsaved contour' in str(widget.saveStatus.text))
    if check_exit:
        red().sliceView().forceRender()
        screenshot = OUTPUT / 'synthetic-draw-unfinished.png'
        slicer.util.mainWindow().grab().save(str(screenshot))
        REPORT['unfinished_screenshot'] = str(screenshot)
    checkpoint = widget.session.current_checkpoint
    widget.nextButton.click()
    events()
    check(key_value + ' Next cannot move unfinished contour', widget.currentSlice == k
          and abs(plane_k(widget) - k) < .001 and pending_points(widget) == 3)
    widget.goSlice(k + 1)
    events()
    check(key_value + ' programmatic navigation also guarded', widget.currentSlice == k
          and pending_points(widget) == 3)
    wheel(widget, vertices[0])
    check(key_value + ' native wheel cannot move unfinished acquired plane',
          widget.currentSlice == k and abs(plane_k(widget) - k) < .001
          and pending_points(widget) == 3)
    widget.labelButtons['lateral'].click()
    widget.toolButtons['Erase'].click()
    widget.saveButton.click()
    widget.reviewButton.click()
    button('Undo').click()
    button('Redo').click()
    events()
    check(key_value + ' label tool Save review history preserve unfinished contour',
          widget.activeLabel == 'medial' and widget.editor.activeEffect().name == 'Draw'
          and pending_points(widget) == 3 and same(arrays(widget), before)
          and widget.session.current_checkpoint == checkpoint)
    slicer.util.mainWindow().close()
    events()
    check(key_value + ' normal window close preserves unfinished contour and work',
          slicer.util.mainWindow().isVisible() and widget.session is not None
          and widget.session.case.key == key_value and pending_points(widget) == 3
          and same(arrays(widget), before))
    if check_exit:
        qt.QApplication.sendEvent(slicer.app, qt.QEvent(qt.QEvent.Quit))
        events()
        check('application Quit event is safely blocked by unfinished contour',
              slicer.util.mainWindow().isVisible() and widget.session is not None
              and pending_points(widget) == 3 and same(arrays(widget), before))
        exit_action = slicer.util.mainWindow().findChild(qt.QAction, 'FileExitAction')
        check('native application File Exit action remains available internally', exit_action is not None)
        exit_action.trigger()
        events()
        check('native File Exit action is safely blocked by unfinished contour',
              slicer.util.mainWindow().isVisible() and widget.session is not None
              and pending_points(widget) == 3 and same(arrays(widget), before))
        transformed_source_guard(widget, vertices, before)
    widget.openCase(other_key)
    events()
    check(key_value + ' case change cannot silently discard or transfer contour',
          widget.session.case.key == key_value and widget.currentSlice == k
          and pending_points(widget) == 3 and same(arrays(widget), before))
    fov = tuple(red().mrmlSliceNode().GetFieldOfView())
    points_before = [tuple(p.rasPoints.GetPoint(i))
                     for p in widget.editor.effectByName('Draw').self().drawPipelines.values()
                     for i in range(p.rasPoints.GetNumberOfPoints())]
    right_drag(widget, vertices[-1])
    points_after = [tuple(p.rasPoints.GetPoint(i))
                    for p in widget.editor.effectByName('Draw').self().drawPipelines.values()
                    for i in range(p.rasPoints.GetNumberOfPoints())]
    check(key_value + ' right drag neither zooms nor fills pending Draw',
          pending_points(widget) == 3 and points_before == points_after
          and np.allclose(fov, red().mrmlSliceNode().GetFieldOfView())
          and same(arrays(widget), before))
    wheel(widget, vertices[-1], control=1)
    check(key_value + ' Ctrl wheel zoom remains usable without moving or committing contour',
          not np.allclose(fov, red().mrmlSliceNode().GetFieldOfView())
          and widget.currentSlice == k and abs(plane_k(widget) - k) < .001
          and pending_points(widget) == 3 and same(arrays(widget), before))
    ancestor = widget.notes.parent()
    while ancestor is not None:
        if hasattr(ancestor, 'collapsed'):
            ancestor.collapsed = False
        ancestor = ancestor.parent() if hasattr(ancestor, 'parent') else None
    widget.notes.show()
    unexpected = []
    note_timer = qt.QTimer()
    note_timer.setInterval(10)
    def reject_note_modal():
        modal = qt.QApplication.activeModalWidget()
        if modal is not None:
            unexpected.append(str(modal.objectName) + ':' + str(modal.windowTitle))
            modal.reject()
    note_timer.connect('timeout()', reject_note_modal)
    shortcut_events, shortcut_callbacks = [], []
    for index, shortcut in enumerate(widget.shortcuts):
        callback = lambda index=index: shortcut_events.append(index)
        shortcut.connect('activated()', callback)
        shortcut_callbacks.append((shortcut, callback))
    note_timer.start()
    try:
        for char in 'dep123rufa':
            key(widget.notes, ord(char.upper()), char)
        for code, text in [(qt.Qt.Key_Left, ''), (qt.Qt.Key_Right, ''),
                           (qt.Qt.Key_Return, '\n'), (qt.Qt.Key_Escape, '')]:
            key(widget.notes, code, text)
        key(widget.notes, qt.Qt.Key_S, 's', qt.Qt.ControlModifier)
        key(widget.notes, qt.Qt.Key_Z, 'z', qt.Qt.ControlModifier)
        key(widget.notes, qt.Qt.Key_Y, 'y', qt.Qt.ControlModifier)
    finally:
        note_timer.stop()
        for shortcut, callback in shortcut_callbacks:
            shortcut.disconnect('activated()', callback)
    check(key_value + ' note typing never fires MRI drawing/navigation/save shortcuts',
          widget.activeLabel == 'medial' and widget.editor.activeEffect().name == 'Draw'
          and widget.currentSlice == k and pending_points(widget) == 3
          and same(arrays(widget), before) and widget.session.current_checkpoint == checkpoint
          and not unexpected and not shortcut_events,
          {'unexpected_modals': unexpected, 'MRI_shortcut_activations': shortcut_events})
    discard(widget, False)
    check(key_value + ' discard cancellation preserves three point contour',
          pending_points(widget) == 3 and same(arrays(widget), before))
    widget.finishContourButton.click()
    events()
    filled = arrays(widget)
    changes = np.argwhere(filled[0] != before[0])
    check(key_value + ' Finish uses native fill on original label and acquired slice',
          pending_points(widget) == 0 and len(changes) > 0
          and set(changes[:, 0]) == {k} and filled[0][k, 63, 14] == 1)
    button('Undo').click()
    events()
    check(key_value + ' guarded Finish Undo restores exact full arrays', same(arrays(widget), before))
    button('Redo').click()
    events()
    check(key_value + ' guarded Finish Redo restores exact full arrays', same(arrays(widget), filled))


def workflow(exit_application):
    source, work = OUTPUT / 'Synthetic source 空間', OUTPUT / 'Synthetic local work'
    dataset, truth = make_draw_matrix(source)
    hashes = {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()}
    (OUTPUT / 'source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    widget = open_widget(source, work)
    keys = [case.key for case in dataset.cases]
    expected = {}
    (OUTPUT / 'Expected').mkdir()
    check('all eight side/direction/obliquity combinations available', len(keys) == 8)
    for ordinal, key_value in enumerate(keys):
        open_case_ui(widget, key_value)
        item = truth[key_value]
        if ordinal == 0:
            widget.notesPanel.collapsed = True
            widget.caseReviewPanel.collapsed = True
            widget.goSlice(item['medial_seed_ijk'][2])
            slicer.util.mainWindow().resize(1280, 800)
            events()
            red().sliceView().forceRender()
            screenshot = OUTPUT / 'synthetic-draw-default.png'
            slicer.util.mainWindow().grab().save(str(screenshot))
            REPORT['default_screenshot'] = str(screenshot)
        check(key_value + ' Draw is default after opening', widget.editor.activeEffect().name == 'Draw')
        check(key_value + ' Draw Erase Paint ordering', list(widget.toolButtons) == ['Draw', 'Erase', 'Paint'])
        check(key_value + ' Draw hides inapplicable brush control', not widget.brushSize.isVisible())
        guidance = instruction(widget)
        check(key_value + ' concise native Draw instruction',
              'Click around the boundary. Right-click to close and fill.' in guidance)
        verify_geometry(widget, key_value, item)
        if item['oblique']:
            stable_contour_view_updates(widget, key_value)
        for endpoint in (0, widget.session.case.n_slices - 1):
            widget.goSlice(endpoint)
            widget._resetView()
            before = arrays(widget)
            check(key_value + ' empty starting slice uses neutral wording ' + str(endpoint),
                  'No starting mask on this slice.' in instruction(widget))
            vertices = [(43, 33, endpoint), (53, 33, endpoint), (53, 43, endpoint), (43, 43, endpoint)]
            points(widget, vertices)
            check(key_value + ' contour preview does not modify endpoint ' + str(endpoint),
                  pending_points(widget) == 4 and same(arrays(widget), before))
            right_click(widget, vertices[-1])
            filled = arrays(widget)
            changes = np.argwhere(filled[0] != before[0])
            check(key_value + ' right click fills only acquired endpoint ' + str(endpoint),
                  pending_points(widget) == 0 and filled[0][endpoint, 38, 48] == 1
                  and len(changes) > 0 and set(changes[:, 0]) == {endpoint})
            button('Undo').click()
            events()
            check(key_value + ' endpoint Draw Undo exact ' + str(endpoint), same(arrays(widget), before))
            button('Redo').click()
            events()
            check(key_value + ' endpoint Draw Redo exact ' + str(endpoint), same(arrays(widget), filled))
            button('Undo').click()
            events()
        for label, value in [('medial', 1), ('lateral', 2)]:
            i, j, k = item[label + '_seed_ijk']
            widget.goSlice(k)
            widget._resetView()
            widget.reviewButton.click()
            widget.goSlice(k)
            before = arrays(widget)
            stroke(widget, (i, j, k), label)
            erased = arrays(widget)
            change = np.argwhere(erased[0] != before[0])
            check(key_value + ' native Erase uses brush only for ' + label,
                  widget.brushSize.isVisible() and len(change) > 0
                  and set(change[:, 0]) == {k} and erased[0][k, j, i] == 0
                  and np.all(before[0][before[0] != erased[0]] == value))
            check(key_value + ' editing reviewed acquired slice invalidates review ' + label,
                  not widget.session.state['review'][k]['reviewed'])
            button('Undo').click()
            events()
            check(key_value + ' Erase Undo exact ' + label, same(arrays(widget), before))
            button('Redo').click()
            events()
            check(key_value + ' Erase Redo exact ' + label, same(arrays(widget), erased))
        contour_guards(widget, key_value, keys[(ordinal + 1) % len(keys)], check_exit=(ordinal == 0))
        k = widget.session.case.n_slices // 2
        widget.goSlice(k)
        widget._resetView()
        before = arrays(widget)
        draw(widget, [(36, 34, k), (40, 34, k), (40, 38, k), (36, 38, k)], 'uncertain')
        uncertain = arrays(widget)
        check(key_value + ' uncertainty is independent of medial/lateral',
              np.array_equal(uncertain[0], before[0]) and uncertain[1][k, 36, 38] == 1
              and set(np.unique(uncertain[0])).issubset({0, 1, 2}))
        button('Undo').click()
        events()
        check(key_value + ' uncertainty Draw Undo exact', same(arrays(widget), before))
        button('Redo').click()
        events()
        check(key_value + ' uncertainty Draw Redo exact', same(arrays(widget), uncertain))
        stroke(widget, (38, 36, k), 'uncertain', diameter=3.)
        check(key_value + ' uncertainty erased without changing anatomy',
              not arrays(widget)[1].any() and np.array_equal(arrays(widget)[0], before[0]))
        widget.notes.setPlainText('SYNTHETIC SOFTWARE QA. No anatomical judgment or research approval.')
        widget.saveButton.click()
        events()
        check(key_value + ' actual Save control reports verified Saved',
              widget.session.current_checkpoint is not None and 'Saved' in str(widget.saveStatus.text)
              and not widget.dirty)
        check(key_value + ' saving does not approve or complete review',
              widget.session.state['status'] != 'practice_approved'
              and not all(row['reviewed'] for row in widget.session.state['review']))
        saved = arrays(widget)
        verify_saved(widget, widget.session.current_checkpoint, saved, key_value + ' saved')
        widget.closeCase()
        open_case_ui(widget, key_value)
        check(key_value + ' existing saved work reopens exactly', same(arrays(widget), saved))
        check(key_value + ' reopened case also defaults Draw', widget.editor.activeEffect().name == 'Draw')
        for acquired in range(widget.session.case.n_slices):
            widget.sliceSlider.setValue(acquired + 1)
            events()
            widget.reviewButton.click()
            events()
        widget.caseReviewPanel.collapsed = False
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        check(key_value + ' research approval blocked for synthetic practice',
              bool(widget.session.approval_errors(*arrays(widget), practice=False)))
        approve(widget)
        check(key_value + ' test approval is not a reader/research approval',
              widget.session.state['status'] == 'practice_approved'
              and widget.session.state['approval']['accepted_research_annotation'] is False
              and widget.session.state['approval']['human_anatomical_approval'] is False)
        expected[key_value] = arrays(widget)
        np.savez_compressed(OUTPUT / 'Expected' / (key_value + '.npz'),
                            labels=expected[key_value][0], uncertainty=expected[key_value][1])
        if ordinal in (0, len(keys) - 1):
            widget.goSlice(k)
            slicer.util.mainWindow().resize(1280 if ordinal == 0 else 1440, 800 if ordinal == 0 else 900)
            events()
            red().sliceView().forceRender()
            slicer.util.mainWindow().grab().save(str(OUTPUT / ('synthetic-draw-case-' + str(ordinal + 1) + '.png')))
    archive_path = export_via_ui(widget)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('actual Export includes all eight approved synthetic cases',
              len(manifest['cases']) == 8 and manifest['software_practice'] is True
              and manifest['accepted_research_annotation'] is False)
        for item in manifest['cases']:
            key_value = item['case_key']
            case = dataset.by_key[key_value]
            for name, expected_array in [('labels.nii.gz', expected[key_value][0]),
                                         ('uncertainty.nii.gz', expected[key_value][1]),
                                         ('validity.nii.gz', np.zeros_like(expected[key_value][0]))]:
                path = OUTPUT / ('export-check-' + key_value + '-' + name)
                path.write_bytes(archive.read(item['folder'] + '/' + name))
                image = nib.load(str(path))
                check(key_value + ' actual ZIP reopens exact full native ' + name,
                      np.array_equal(np.asarray(image.dataobj).transpose(2, 1, 0), expected_array)
                      and image.shape == case.shape_xyz and np.allclose(image.affine, case.affine_ras, atol=1e-4))
            for role in ('medial', 'lateral'):
                point = truth[key_value][role + '_seed_ijk']
                check(key_value + ' exported physical coordinate ' + role,
                      np.allclose((image.affine @ [*point, 1])[:3],
                                  truth[key_value][role + '_seed_ras_mm'], atol=1e-4))
    check('all synthetic input files remain byte identical',
          hashes == {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()})
    check('application source stayed fixed through native workflow',
          sha256(REPORT['application_source_path']) == REPORT['application_source_sha256']
          and sha256(REPORT['core_source_path']) == REPORT['core_source_sha256'])
    (OUTPUT / 'expected-cases.json').write_text(json.dumps(keys, indent=2) + '\n')
    widget.goSlice(widget.session.case.n_slices // 2)
    widget.settings.sync()
    REPORT['close_route'] = 'normal main-window close' if exit_application else 'guarded case close; installed caller owns process exit'
    if exit_application:
        slicer.util.mainWindow().close()
        events()
    else:
        widget.closeCase()
    check('completed workflow releases annotation case lock', widget.session is None)


def resume():
    previous = json.loads((OUTPUT / 'draw-workflow.json').read_text())
    check('resume requires successful current matrix workflow', previous.get('passed') is True)
    widget = open_widget(OUTPUT / 'Synthetic source 空間', OUTPUT / 'Synthetic local work')
    check('cold process uses the same tested application files',
          REPORT['application_source_sha256'] == previous['application_source_sha256']
          and REPORT['core_source_sha256'] == previous['core_source_sha256'])
    truth = json.loads((OUTPUT / 'Synthetic source 空間' / 'synthetic_truth.json').read_text())
    keys = json.loads((OUTPUT / 'expected-cases.json').read_text())
    for key_value in keys:
        open_case_ui(widget, key_value)
        affine = widget.session.case.affine_ras
        normal = affine[:3, 2] / np.linalg.norm(affine[:3, 2])
        up = affine[:3, 1] / np.linalg.norm(affine[:3, 1])
        if up[2] < 0:
            up = -up
        expected_frame = np.column_stack([np.cross(up, normal), up, normal])
        check(key_value + ' cold displayed basis matches verified physical frame',
              np.allclose(matrix(red().mrmlSliceNode().GetSliceToRAS())[:3, :3],
                          expected_frame, atol=1e-5, rtol=0))
        expected = np.load(OUTPUT / 'Expected' / (key_value + '.npz'))
        value = (expected['labels'], expected['uncertainty'])
        check(key_value + ' cold process restores exact arrays', same(arrays(widget), value))
        check(key_value + ' cold process restores Draw default', widget.editor.activeEffect().name == 'Draw')
        verify_saved(widget, widget.session.current_checkpoint, value, key_value + ' cold')
        for role in ('medial', 'lateral'):
            point = truth[key_value][role + '_seed_ijk']
            check(key_value + ' cold physical point ' + role,
                  np.allclose((widget.session.case.affine_ras @ [*point, 1])[:3],
                              truth[key_value][role + '_seed_ras_mm'], atol=1e-4))
    hashes = json.loads((OUTPUT / 'source-hashes.json').read_text())
    source = OUTPUT / 'Synthetic source 空間'
    check('cold restart leaves input package unchanged',
          hashes == {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()})
    widget.closeCase()


def layout():
    widget = open_widget(OUTPUT / 'Synthetic source 空間', OUTPUT / 'Synthetic local work')
    open_case_ui(widget, widget.dataset.cases[0].key)
    window = slicer.util.mainWindow()
    # Native Slicer can restore fullscreen/window geometry late in startup.
    # Test ordinary resizable windows only after leaving that native state.
    window.showNormal()
    startup_until = time.monotonic() + 1
    while time.monotonic() < startup_until:
        events()
        time.sleep(.01)
    widget.notesPanel.collapsed = True
    widget.caseReviewPanel.collapsed = True
    REPORT['scale_scope'] = ('QT_SCALE_FACTOR simulation in an actual desktop process; '
                             'not human review or native Windows display-setting acceptance')
    REPORT['scale_factor_environment'] = os.environ.get('QT_SCALE_FACTOR')
    REPORT['layouts'] = []
    for width, height in [(1280, 800), (1366, 768), (1440, 900), (1024, 640)]:
        window.resize(width, height)
        events()
        red().sliceView().forceRender()
        controls = [widget.identityLabel, widget.saveStatus, widget.sliceReadout, widget.sliceSlider, widget.previousButton,
                    widget.nextButton, widget.saveButton, widget.reviewButton,
                    button('Undo'), button('Redo'),
                    *widget.toolButtons.values(), *widget.labelButtons.values()]
        screen = window.screen().availableGeometry if hasattr(window, 'screen') else qt.QApplication.desktop().availableGeometry(window)
        actual = [window.width, window.height]
        entry = {'requested_logical_size': [width, height], 'actual_logical_size': actual,
                 'screen_available': [screen.width(), screen.height()],
                 'fits_available_desktop': actual[0] <= screen.width() and actual[1] <= screen.height(),
                 'device_pixel_ratio': window.devicePixelRatioF(),
                 'window_state': int(window.windowState()),
                 'controls': []}
        scroll = widget.rightDock.findChild(qt.QScrollArea)
        if scroll is not None:
            def describe(item):
                result = {'class': type(item).__name__, 'size': [item.width, item.height]}
                for attribute in ('minimumSize', 'minimumSizeHint', 'sizeHint'):
                    value = getattr(item, attribute)
                    value = value() if callable(value) else value
                    result[attribute] = [value.width(), value.height()]
                return result
            entry['right_panel'] = {'dock': describe(widget.rightDock),
                                    'scroll': describe(scroll),
                                    'viewport': describe(scroll.viewport()),
                                    'panel': describe(scroll.widget()),
                                    'labels': [{'text': str(label.text), **describe(label)}
                                               for label in scroll.widget().findChildren(qt.QLabel)
                                               if label.isVisible()]}
            panel_layout = scroll.widget().layout()
            entry['right_panel']['direct_layout_items'] = []
            for index in range(panel_layout.count()):
                item = panel_layout.itemAt(index)
                owner = item.widget()
                item_entry = {'index': index,
                              'minimum': [item.minimumSize().width(), item.minimumSize().height()],
                              'hint': [item.sizeHint().width(), item.sizeHint().height()]}
                if owner is not None:
                    item_entry.update({'widget': type(owner).__name__,
                                       'text': str(getattr(owner, 'text', ''))})
                else:
                    item_entry['widget'] = 'layout_or_spacer'
                entry['right_panel']['direct_layout_items'].append(item_entry)
        REPORT['layouts'].append(entry)
        for control in controls:
            origin = control.mapTo(window, qt.QPoint(0, 0))
            rect = qt.QRect(origin, control.size)
            contained = window.rect.contains(rect)
            clipped_ancestors = []
            ancestor = control.parentWidget()
            while ancestor is not None and ancestor != window:
                ancestor_rect = qt.QRect(control.mapTo(ancestor, qt.QPoint(0, 0)), control.size)
                if not ancestor.rect.contains(ancestor_rect):
                    clipped_ancestors.append(str(ancestor.objectName) or type(ancestor).__name__)
                ancestor = ancestor.parentWidget()
            visible_bounds = control.visibleRegion().boundingRect()
            fully_visible = visible_bounds.contains(control.rect)
            entry['controls'].append({'text': str(getattr(control, 'text', '')),
                                      'visible': control.isVisible(), 'contained': contained,
                                      'fully_visible_region': fully_visible,
                                      'clipped_ancestors': clipped_ancestors,
                                      'size': [control.width, control.height]})
            check('scale ' + SCALE_NAME + ' essential control visible and contained ' + str(getattr(control, 'text', 'slider')),
                  control.isVisible() and contained and not clipped_ancestors and fully_visible,
                  entry['controls'][-1])
        scrollbars = [bar for bar in window.findChildren(qt.QScrollBar)
                      if bar.orientation == qt.Qt.Horizontal and bar.isVisible() and bar.maximum > 0]
        check('scale ' + SCALE_NAME + ' no horizontal panel scrolling', not scrollbars)
        check('scale ' + SCALE_NAME + ' Draw brush row remains hidden', not widget.brushSize.isVisible())
        window.grab().save(str(OUTPUT / ('synthetic-draw-layout-' + SCALE_NAME + '-' + str(width) + '.png')))
        k = widget.currentSlice
        points(widget, [(43, 33, k), (53, 33, k), (48, 43, k)])
        settle_until = time.monotonic() + .2
        while time.monotonic() < settle_until:
            events()
            time.sleep(.01)
        # A native startup/window-restore callback can run after the first
        # pending contour changes the toolbar's size hint. Reassert the test
        # size after that settles; record the actual pending geometry too.
        window.resize(width, height)
        settle_until = time.monotonic() + .2
        while time.monotonic() < settle_until:
            events()
            time.sleep(.01)
        red().sliceView().forceRender()
        entry['pending_actual_logical_size'] = [window.width, window.height]
        entry['pending_controls'] = []
        pending_controls = [widget.finishContourButton, widget.discardContourButton, widget.instruction,
                            widget.saveButton, widget.reviewButton, widget.sliceReadout]
        pending_controls += [control for control in (widget.progress, widget.sliceState) if control.isVisible()]
        for control in pending_controls:
            rect = qt.QRect(control.mapTo(window, qt.QPoint(0, 0)), control.size)
            detail = {'text': str(getattr(control, 'text', '')),
                      'window_rect': [rect.x(), rect.y(), rect.width(), rect.height()],
                      'visible': control.isVisible(),
                      'contained': window.rect.contains(rect),
                      'fully_visible_region': control.visibleRegion().boundingRect().contains(control.rect)}
            entry['pending_controls'].append(detail)
            check('scale ' + SCALE_NAME + ' pending contour guidance/control remains visible ' + str(getattr(control, 'text', '')),
                  detail['visible'] and detail['contained'] and detail['fully_visible_region'], detail)
        window.grab().save(str(OUTPUT / ('synthetic-draw-pending-' + SCALE_NAME + '-' + str(width) + '.png')))
        discard(widget, True)
        widget.notesPanel.collapsed = False
        widget.caseReviewPanel.collapsed = False
        events()
        if scroll is not None:
            scroll.ensureWidgetVisible(widget.approveButton)
        events()
        check('scale ' + SCALE_NAME + ' approval is reachable in expanded case details',
              widget.approveButton.isVisible()
              and widget.approveButton.visibleRegion().boundingRect().contains(widget.approveButton.rect))
        window.grab().save(str(OUTPUT / ('synthetic-draw-details-' + SCALE_NAME + '-' + str(width) + '.png')))
        widget.notesPanel.collapsed = True
        widget.caseReviewPanel.collapsed = True
        if scroll is not None:
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().minimum)
        events()
    widget.closeCase()


def window_geometry_trace():
    """Separate native startup/window-state restoration from pending layout."""
    widget = open_widget(OUTPUT / 'Synthetic source 空間', OUTPUT / 'Synthetic local work')
    open_case_ui(widget, widget.dataset.cases[0].key)
    window = slicer.util.mainWindow()
    REPORT['window_geometry_trace'] = []

    def wait(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            events()
            time.sleep(.01)

    def record(stage):
        item = {'stage': stage, 'size': [window.width, window.height],
                'window_state': int(window.windowState()), 'maximized': window.isMaximized(),
                'pending_points': pending_points(widget),
                'normal_geometry': [window.normalGeometry.x(), window.normalGeometry.y(),
                                    window.normalGeometry.width(), window.normalGeometry.height()],
                'frame_geometry': [window.frameGeometry.x(), window.frameGeometry.y(),
                                   window.frameGeometry.width(), window.frameGeometry.height()]}
        for name in ('minimumSize', 'minimumSizeHint', 'sizeHint'):
            value = getattr(window, name)
            value = value() if callable(value) else value
            item[name] = [value.width(), value.height()]
        REPORT['window_geometry_trace'].append(item)

    wait(1)
    record('startup_settled')
    for normalize in (False, True):
        prefix = 'normal_' if normalize else 'existing_state_'
        if normalize:
            window.showNormal()
            wait(.2)
        window.resize(1280, 800)
        wait(1)
        record(prefix + 'baseline_1280_after_1s')
        k = widget.currentSlice
        points(widget, [(43, 33, k), (53, 33, k), (48, 43, k)])
        record(prefix + 'pending_immediate')
        wait(.2)
        record(prefix + 'pending_after_0.2s')
        wait(.8)
        record(prefix + 'pending_after_1s')
        window.resize(1280, 800)
        wait(.2)
        record(prefix + 'pending_after_resize_attempt')
        discard(widget, True)
        wait(.2)
        record(prefix + 'after_discard')
    widget.closeCase()


def run_phase(exit_application=True):
    global REPORT
    for protected in (TEST_DIR.parent, Path(inspect.getsourcefile(Dataset)).resolve().parent.parent):
        try:
            OUTPUT.relative_to(protected)
        except ValueError:
            continue
        raise ValueError('Synthetic outputs must stay outside source and installed application files.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT = {'phase': PHASE, 'checks': [], 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'slicer_version': slicer.app.applicationVersion, 'slicer_revision': slicer.app.repositoryRevision,
              'platform': platform.platform(), 'machine': platform.machine(),
              'scope': 'Procedural synthetic software-practice only; injected native Qt/VTK events, not human/anatomical/Windows acceptance.'}
    suffix = ('-' + SCALE_NAME) if PHASE == 'layout' else ''
    destination = OUTPUT / ('draw-' + PHASE + suffix + '.json')
    try:
        if PHASE == 'workflow':
            workflow(exit_application)
        elif PHASE == 'resume':
            resume()
        elif PHASE == 'layout':
            layout()
        elif PHASE == 'window_geometry':
            window_geometry_trace()
        else:
            raise ValueError('Unknown synthetic Draw test phase.')
        REPORT['passed'] = True
    except Exception:
        REPORT['passed'] = False
        REPORT['error'] = traceback.format_exc()
        slicer.util.mainWindow().grab().save(str(OUTPUT / ('synthetic-draw-failure-' + PHASE + '.png')))
        if WIDGET:
            # Cleanup only this harness's synthetic fixtures; never touches a
            # pre-existing reader window or work folder.
            try:
                for pipeline in WIDGET.editor.effectByName('Draw').self().drawPipelines.values():
                    pipeline.resetPolyData()
                WIDGET._loading = True
                WIDGET.dirty = False
                WIDGET.closeCase()
            except Exception:
                REPORT['cleanup_error'] = traceback.format_exc()
    REPORT['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    destination.write_text(json.dumps(REPORT, indent=2) + '\n')
    print('MENISCUS_DRAW_RESULT', json.dumps({'phase': PHASE, 'passed': REPORT['passed'],
                                             'checks': len(REPORT['checks']), 'report': str(destination)}), flush=True)
    if exit_application:
        slicer.app.exit(0 if REPORT['passed'] else 1)
    return REPORT


if __name__ == '__main__':
    run_phase(exit_application=os.environ.get('MENISCUS_DRAW_MANAGED') != '1')
