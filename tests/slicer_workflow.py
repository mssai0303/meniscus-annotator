"""Integration checks executed INSIDE the pinned Slicer desktop runtime.

Launch with the module directory supplied via --additional-module-paths. This
exercises real MRML nodes, native editor effects and the focused module. It is
not a substitute for the manual Windows acceptance list in docs/TEST_PLAN.md.
Only synthetic fixtures are generated. Results and screenshots stay in the
MENISCUS_TEST_OUTPUT directory (defaults to a temporary local directory).
"""
import csv
import json
import os
import re
import platform
from pathlib import Path
import sys
import tempfile
import zipfile
import traceback

import numpy as np
import qt
import slicer
import vtk

REPO = Path(__file__).resolve().parents[1] if '__file__' in globals() else Path(os.environ['MENISCUS_REPO'])
sys.path.insert(0, str(REPO))
OUTPUT = Path(os.environ.get('MENISCUS_TEST_OUTPUT', tempfile.mkdtemp(prefix='meniscus-slicer-results-')))
OUTPUT.mkdir(parents=True, exist_ok=True)
# Isolate the widget's plain qt.QSettings as well as Slicer's own --testing
# settings. Reuse only this synthetic directory during a fresh-process restart.
SETTINGS_ROOT = Path(os.environ.get('MENISCUS_RESUME_FROM', str(OUTPUT))) / 'Qt settings'
SETTINGS_ROOT.mkdir(parents=True, exist_ok=True)
qt.QSettings.setDefaultFormat(qt.QSettings.IniFormat)
qt.QSettings.setPath(qt.QSettings.IniFormat, qt.QSettings.UserScope, str(SETTINGS_ROOT))
SETTINGS_FILE = Path(os.environ.get('MENISCUS_TEST_SETTINGS_FILE', str(SETTINGS_ROOT / 'workflow.ini')))
REPORT = {'platform': sys.platform, 'os': platform.platform(), 'machine': platform.machine(), 'slicer_version': slicer.app.applicationVersion,
          'slicer_revision': slicer.app.repositoryRevision, 'checks': [],
          'scope': 'Synthetic development integration; neither anatomical validation nor Windows installer acceptance.',
          'settings_scope': 'Isolated Qt settings under synthetic output; no production settings changed.'}


def check(name, condition, detail=''):
    REPORT['checks'].append({'name': name, 'passed': bool(condition), 'detail': detail})
    if not condition:
        raise AssertionError(name + ': ' + detail)


def events():
    slicer.app.processEvents()


def plain_label(label):
    return re.sub(r'<[^>]+>', '', str(label.text)).strip()


def key_event(target, key):
    """Deliver a key to the actual focused Qt widget, not a helper callback."""
    target.setFocus()
    for event_type in (qt.QEvent.KeyPress, qt.QEvent.KeyRelease):
        qt.QApplication.sendEvent(target, qt.QKeyEvent(event_type, key, qt.Qt.NoModifier))
    events()


def check_workspace(widget):
    window = slicer.util.mainWindow()
    names = [plain_label(label) for label in window.findChildren(qt.QLabel) if label.isVisible()]
    check('workspace header identifies Meniscus Annotator', 'Meniscus Annotator' in names)
    check('workspace window title identifies actual application', str(window.windowTitle).startswith('Meniscus Annotator'))
    unrelated = [str(bar.objectName) for bar in window.findChildren(qt.QToolBar)
                 if bar.isVisible() and not str(bar.objectName).startswith('Meniscus')]
    check('workspace hides unrelated Slicer toolbars', not unrelated, str(unrelated))
    check('workspace displays save state', widget.saveStatus.isVisible() and bool(plain_label(widget.saveStatus)))
    check('workspace exposes acquired-slice slider and readout', widget.sliceSlider.isVisible() and widget.sliceReadout.isVisible())


def xy_for_ijk(widget, ijk):
    """Map a known native voxel to real slice-renderer display coordinates."""
    ijk_to_ras = vtk.vtkMatrix4x4()
    widget.volume.GetIJKToRASMatrix(ijk_to_ras)
    world = ijk_to_ras.MultiplyPoint([*ijk, 1])
    red = slicer.app.layoutManager().sliceWidget('Red')
    inverse = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(red.mrmlSliceNode().GetXYToRAS(), inverse)
    xy = inverse.MultiplyPoint(world)
    return tuple(int(round(x)) for x in xy[:2])


def stroke(widget, ijk, tool='Paint', label='medial', flush=True):
    """Drive the installed native Slicer effect through actual VTK view events."""
    widget.setLabel(label)
    widget.setTool(tool)
    effect = widget.editor.activeEffect()
    widget.brushSize.setValue(2.0)
    effect.setParameter('BrushSphere', 0)
    effect.setParameter('EditIn3DViews', 0)
    effect.setParameter('BrushDiameterIsRelative', 0)
    effect.setParameter('BrushAbsoluteDiameter', 2.0)
    red = slicer.app.layoutManager().sliceWidget('Red')
    xy = xy_for_ijk(widget, ijk)
    interactor = red.sliceView().interactorStyle().GetInteractor()
    interactor.SetEventInformation(xy[0], xy[1], 0, 0)
    for name in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
        interactor.InvokeEvent(name)
    if flush:
        events()
    return xy


def draw(widget, points):
    widget.setLabel('medial')
    widget.setTool('Draw')
    red = slicer.app.layoutManager().sliceWidget('Red')
    interactor = red.sliceView().interactorStyle().GetInteractor()
    for ijk in points:
        x, y = xy_for_ijk(widget, ijk)
        interactor.SetEventInformation(x, y, 0, 0)
        interactor.InvokeEvent('LeftButtonPressEvent')
        interactor.InvokeEvent('LeftButtonReleaseEvent')
    interactor.InvokeEvent('RightButtonPressEvent')
    interactor.InvokeEvent('RightButtonReleaseEvent')
    events()


def run():
    # Import only our committed synthetic generator; never inspect a nearby MRI.
    from tools.make_synthetic import make_synthetic
    from MeniscusAnnotatorLib.core import sha256, export_approved, Dataset, WorkStore, write_native
    import nibabel as nib
    import SimpleITK as sitk
    if os.environ.get('MENISCUS_RESUME_FROM'):
        previous = Path(os.environ['MENISCUS_RESUME_FROM'])
        slicer.util.selectModule('MeniscusAnnotator')
        widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
        widget.settings = qt.QSettings(str(SETTINGS_FILE), qt.QSettings.IniFormat)  # Exact file also survives --testing's different application name.
        widget.openDataset(str(previous / 'Synthetic dataset 空間'), work_root=str(previous / 'Local work Jeff'))
        widget._resume()
        events()
        check('restart resumes last case', widget.session.case.key == widget.dataset.cases[-1].key)
        check('restart preserves close-saved notes', widget.session.state['notes'] == 'Synthetic close persistence probe')
        check('restart resumes acquired slice', widget.currentSlice == widget.session.case.n_slices // 2)
        labels, uncertain = widget.collectArrays()
        saved_labels, saved_uncertain, _ = widget.session.load()
        check('restart restores saved native masks', np.array_equal(labels,saved_labels) and np.array_equal(uncertain,saved_uncertain))
        widget.caseListDock.setVisible(False)
        widget.rightDock.setVisible(False)
        events()
        red = slicer.app.layoutManager().sliceWidget('Red')
        red.sliceView().forceRender()
        annotation = red.sliceView().cornerAnnotation()
        active_overlay = annotation.GetText(vtk.vtkCornerAnnotation.UpperRight)
        check('collapsed tools retain active label and editing scope on canvas', 'Medial meniscus' in active_overlay and 'Paint' in active_overlay and 'This slice only' in active_overlay)
        check('collapsed panels retain acquired-slice readout and slider', widget.sliceReadout.isVisible() and widget.sliceSlider.isVisible() and str(widget.currentSlice+1) in plain_label(widget.sliceReadout))
        matrix = red.mrmlSliceNode().GetSliceToRAS()
        point = np.array([matrix.GetElement(axis,3) for axis in range(3)]+[1])
        native_index = (np.linalg.inv(widget.session.case.affine_ras) @ point)[2]
        check('collapsed panels preserve the acquired editing plane', abs(native_index-widget.currentSlice)<0.001)
        slicer.util.mainWindow().grab().save(str(OUTPUT / 'synthetic-panels-collapsed.png'))
        widget.caseListDock.setVisible(True)
        widget.rightDock.setVisible(True)
        events()
        widget.closeCase()
        REPORT['passed'] = True
        return
    dataset_root = OUTPUT / 'Synthetic dataset 空間'
    work_root = OUTPUT / 'Local work Jeff'
    layout = os.environ.get('MENISCUS_TEST_LAYOUT', 'legacy')
    REPORT['folder_layout'] = layout
    make_synthetic(dataset_root, layout=layout)
    # Nearby masks are intentionally present but never configured as permitted input.
    fixture_dataset = Dataset(dataset_root)
    # Explicit automated practice attribution: never confirm that a synthetic
    # test is the human reader, and never rely on an implicit blank fallback.
    software_context = {'purpose': 'software_practice', 'actor_type': 'automated',
                        'actor': 'Software QA (automated)'}
    blank_job = {'schema_version': 'meniscus_job/1', 'dataset_identity': fixture_dataset.identity,
                 'protocol': {'version': 'SYNTHETIC-BLANK-SOFTWARE-1', 'status': 'draft'},
                 'practice_context': software_context,
                 'cases': {case.key: {'annotation_mode': 'blank'} for case in fixture_dataset.cases}}
    blank_job_path = OUTPUT / 'synthetic_software_job.json'
    blank_job_path.write_text(json.dumps(blank_job, indent=2) + '\n', encoding='utf-8')
    for fixture_case in fixture_dataset.cases:
        phantom_prediction = np.full(fixture_case.shape_xyz[::-1], 2, dtype=np.uint8)
        nearby = fixture_case.folder / 'annotations' if layout == 'legacy' else dataset_root / 'Unconfigured predictions' / fixture_case.key
        nearby.mkdir(parents=True, exist_ok=True)
        write_native(nearby / 'prediction.nii.gz', phantom_prediction, fixture_case)
    source_hashes = {str(p.relative_to(dataset_root)): sha256(p) for p in dataset_root.rglob('*') if p.is_file()}
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    widget.settings = qt.QSettings(str(SETTINGS_FILE), qt.QSettings.IniFormat)  # Bind even if direct startup constructed the widget earlier.
    widget.settings.setValue('Meniscus/job/' + fixture_dataset.identity, str(blank_job_path))
    widget.openDataset(str(dataset_root), work_root=str(work_root))
    events()
    # Select all generated geometries including oblique, variable dimensions/counts.
    keys = [case.key for case in widget.dataset.cases]
    approved_arrays = {}
    check('synthetic cases available', len(keys) >= 2)
    check_workspace(widget)
    for key in keys:
        widget.openCase(key)
        events()
        dims = widget.volume.GetImageData().GetDimensions()
        k = dims[2] // 2
        i, j = dims[0] // 2, dims[1] // 2
        check(key + ' slider spans every acquired slice', widget.sliceSlider.minimum == 1 and widget.sliceSlider.maximum == dims[2])
        selected = {widget.caseTable.item(index.row(),0).data(qt.Qt.UserRole) for index in widget.caseTable.selectedIndexes()}
        check(key + ' current case is visibly selected', key in selected)
        all_planes_match = True
        plane_checks = []
        all_readouts_match = True
        affine = widget.session.case.affine_ras
        normal = affine[:3,2] / np.linalg.norm(affine[:3,2])
        initial_matrix = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode().GetSliceToRAS()
        initial_point = np.array([initial_matrix.GetElement(axis,3) for axis in range(3)]+[1])
        check(key + ' initial displayed slice matches loaded native plane', abs((np.linalg.inv(affine) @ initial_point)[2]-widget.currentSlice) < 0.001)
        for endpoint in (0,dims[2]-1):
            if widget.currentSlice != endpoint:
                widget.goSlice(endpoint)
            stroke(widget,(i,j,endpoint))
            endpoint_labels, _ = widget.collectArrays()
            painted_indices = np.argwhere(endpoint_labels > 0)
            check(key + ' native Paint isolates endpoint slice ' + str(endpoint+1), len(painted_indices)>0 and set(painted_indices[:,0])=={endpoint} and endpoint_labels[endpoint,j,i]==1)
            widget.editor.undo()
            events()
            endpoint_undone, _ = widget.collectArrays()
            check(key + ' endpoint paint Undo restores empty annotation ' + str(endpoint+1), not endpoint_undone.any())
        for acquired_index in range(dims[2]):
            widget.sliceSlider.setValue(acquired_index+1)
            events()
            numbers = [int(n) for n in re.findall(r'\d+', plain_label(widget.sliceReadout))]
            all_readouts_match &= 'slice' in plain_label(widget.sliceReadout).lower() and len(numbers) >= 2 and numbers[0] == acquired_index+1 and numbers[-1] == dims[2]
            matrix = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode().GetSliceToRAS()
            plane_origin = np.array([matrix.GetElement(axis,3) for axis in range(3)])
            expected_origin = (affine @ np.array([0,0,acquired_index,1]))[:3]
            error_mm = float(abs(np.dot(normal, plane_origin-expected_origin)))
            current_match = widget.currentSlice == acquired_index and error_mm < 0.001
            all_planes_match &= current_match
            plane_checks.append({'display_requested':acquired_index+1,'current_k':widget.currentSlice,'slider':widget.sliceSlider.value,'native_k':float((np.linalg.inv(affine) @ np.r_[plane_origin,1])[2]),'plane_error_mm':error_mm,'readout':plain_label(widget.sliceReadout)})
        REPORT.setdefault('native_plane_checks',{})[key] = plane_checks
        check(key + ' every acquired slice maps to native plane', all_planes_match, json.dumps([x for x in plane_checks if x['plane_error_mm']>=0.001 or x['current_k'] != x['display_requested']-1]))
        check(key + ' every slider position displays human slice and total', all_readouts_match, plain_label(widget.sliceReadout))
        key_event(widget.sliceSlider, qt.Qt.Key_Home)
        check(key + ' slider Home reaches first acquired slice', widget.currentSlice == 0 and widget.sliceSlider.value == 1)
        key_event(widget.sliceSlider, qt.Qt.Key_End)
        check(key + ' slider End reaches last acquired slice', widget.currentSlice == dims[2]-1 and widget.sliceSlider.value == dims[2])
        widget.goSlice(2)
        widget._resetView()
        reset_matrix = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode().GetSliceToRAS()
        reset_point = np.array([reset_matrix.GetElement(axis,3) for axis in range(3)]+[1])
        check(key + ' Reset view preserves requested acquired slice', widget.currentSlice == 2 and abs((np.linalg.inv(affine) @ reset_point)[2]-2) < 0.001)
        widget.goSlice(k)
        events()
        primary_view = slicer.app.layoutManager().sliceWidget('Red').sliceView()
        key_event(primary_view, qt.Qt.Key_Right)
        check(key + ' canvas Right steps one acquired slice', widget.currentSlice == k+1 and widget.sliceSlider.value == k+2)
        key_event(primary_view, qt.Qt.Key_Left)
        check(key + ' canvas Left steps one acquired slice', widget.currentSlice == k and widget.sliceSlider.value == k+1)
        before, _ = widget.collectArrays()
        check(key + ' blank mode ignores nearby prediction', not np.any(before))
        check(key + ' prediction-free scene contains source MRI only', slicer.mrmlScene.GetNodesByClass('vtkMRMLScalarVolumeNode').GetNumberOfItems() == 1)
        widget.save()
        blank_checkpoint = widget.session.current_checkpoint
        blank_image = sitk.ReadImage(str(blank_checkpoint / 'labels.nii.gz'))
        check(key + ' empty annotation exports full native dimensions', blank_image.GetSize() == dims and not sitk.GetArrayFromImage(blank_image).any())
        metadata = widget.session.case.metadata
        check(key + ' empty annotation exports native physical grid', np.allclose(blank_image.GetSpacing(),metadata['spacing_xyz_mm'],atol=1e-5) and np.allclose(blank_image.GetOrigin(),metadata['origin_lps_mm'],atol=1e-4) and np.allclose(np.array(blank_image.GetDirection()).reshape(3,3),metadata['direction_lps_columns'],atol=1e-5))
        widget.closeCase()
        widget.openCase(key)
        widget.goSlice(k)
        events()
        blank_labels, blank_uncertainty = widget.collectArrays()
        check(key + ' completely empty segmentation saves and reopens', not blank_labels.any() and not blank_uncertainty.any() and blank_labels.shape == dims[::-1])
        # Orientation reformats cannot become accidental editing surfaces.
        widget.reformats.setChecked(True)
        events()
        for view_name in ['Yellow', 'Green']:
            secondary = slicer.app.layoutManager().sliceWidget(view_name)
            interactor = secondary.sliceView().interactorStyle().GetInteractor()
            size = secondary.sliceView().renderWindow().GetSize()
            interactor.SetEventInformation(size[0]//2, size[1]//2, 0, 0)
            for event_name in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
                interactor.InvokeEvent(event_name)
            events()
        after_reformat, _ = widget.collectArrays()
        check(key + ' secondary reformats reject editing', np.array_equal(before, after_reformat))
        widget.reformats.setChecked(False)
        widget.goSlice(k)
        events()
        # Letters used as canvas shortcuts must remain ordinary text in notes.
        old_label, old_tool, old_slice = widget.activeLabel, widget.editor.activeEffect().name, widget.currentSlice
        widget.notes.setFocus()
        for text in 'pderuf123':
            press = qt.QKeyEvent(qt.QEvent.KeyPress, ord(text.upper()), qt.Qt.NoModifier, text)
            release = qt.QKeyEvent(qt.QEvent.KeyRelease, ord(text.upper()), qt.Qt.NoModifier, text)
            qt.QApplication.sendEvent(widget.notes, press)
            qt.QApplication.sendEvent(widget.notes, release)
        events()
        check(key + ' notes accept shortcut letters', str(widget.notes.toPlainText()).endswith('pderuf123'))
        check(key + ' notes typing does not navigate or switch tools', (widget.activeLabel, widget.editor.activeEffect().name, widget.currentSlice) == (old_label, old_tool, old_slice))
        widget.notes.clear()
        slicer.app.layoutManager().sliceWidget('Red').sliceView().setFocus()
        stroke(widget, (i, j, k))
        after, _ = widget.collectArrays()
        changed = np.argwhere(before != after)
        check(key + ' native Paint changes voxels', len(changed) > 0)
        check(key + ' Paint affects intended acquired slice only', set(changed[:, 0]) == {k}, str(np.unique(changed[:, 0])))
        check(key + ' known voxel painted medial', after[k, j, i] == 1)
        widget.editor.undo()
        events()
        undone, _ = widget.collectArrays()
        check(key + ' undo restores blank', np.array_equal(before, undone))
        widget.editor.redo()
        events()
        redone, _ = widget.collectArrays()
        check(key + ' redo restores paint', np.array_equal(after, redone))
        widget._reviewNext()
        events()
        check(key + ' Reviewed next records explicit review', widget.session.state['review'][k]['reviewed'])
        check(key + ' Reviewed next advances one acquired slice', widget.currentSlice == k+1)
        widget.goSlice(k)
        events()
        stroke(widget, (i, j, k), label='lateral')
        check(key + ' edit invalidates reviewed slice', not widget.session.state['review'][k]['reviewed'])
        lateral, _ = widget.collectArrays()
        check(key + ' lateral replaces medial with fixed value 2', lateral[k, j, i] == 2)
        widget.editor.undo()
        events()
        overlap_undone, _ = widget.collectArrays()
        check(key + ' compartment overwrite undo restores prior anatomy', np.array_equal(overlap_undone, after))
        widget.editor.redo()
        events()
        overlap_redone, _ = widget.collectArrays()
        check(key + ' compartment overwrite redo restores replacement', np.array_equal(overlap_redone, lateral))
        stroke(widget, (i, j, k), tool='Erase', label='lateral')
        erased, _ = widget.collectArrays()
        check(key + ' erase removes lateral', erased[k, j, i] == 0)
        widget.editor.undo()
        events()
        restore, _ = widget.collectArrays()
        check(key + ' erase undo restores label', restore[k, j, i] == 2)
        stroke(widget, (i, j, k), label='uncertain')
        widget.setLabel('lateral')
        widget.editor.undo()
        events()
        after_switch_undo, after_switch_uncertainty = widget.collectArrays()
        check(key + ' undo survives switching uncertainty label', after_switch_undo[k, j, i] == 2 and not after_switch_uncertainty.any())
        widget.editor.redo()
        events()
        labels, uncertain = widget.collectArrays()
        check(key + ' separate uncertainty exists', np.any(uncertain))
        check(key + ' uncertainty overlaps anatomy without erasing it', uncertain[k,j,i] == 1 and labels[k,j,i] == 2)
        stroke(widget, (i,j,k), label='medial')
        labels, uncertain = widget.collectArrays()
        check(key + ' anatomical edit preserves overlapping uncertainty', labels[k,j,i] == 1 and uncertain[k,j,i] == 1)
        check(key + ' uncertainty does not add training class', set(np.unique(labels)).issubset({0, 1, 2}))
        # Draw a separate contour through the actual native Draw effect.
        draw(widget, [(i-7, j-7, k), (i-3, j-7, k), (i-3, j-3, k), (i-7, j-3, k)])
        drawn, _ = widget.collectArrays()
        check(key + ' Draw contour fills known native voxel', drawn[k, j-5, i-5] == 1)
        check(key + ' Draw stays on acquired slice', set(np.argwhere(drawn != labels)[:, 0]) == {k})
        widget.save()
        saved_labels, saved_uncertain = widget.collectArrays()
        checkpoint = widget.session.current_checkpoint
        for name, expected in [('labels.nii.gz', saved_labels), ('uncertainty.nii.gz', saved_uncertain)]:
            independently_read = nib.load(str(checkpoint / name))
            check(key + ' independent reopen ' + name, np.array_equal(np.asarray(independently_read.dataobj).transpose(2, 1, 0), expected))
            check(key + ' independent full geometry ' + name, independently_read.shape == dims and np.allclose(independently_read.affine, widget.session.case.affine_ras, atol=1e-5))
            sitk_image = sitk.ReadImage(str(checkpoint / name))
            check(key + ' SimpleITK voxels ' + name, np.array_equal(sitk.GetArrayFromImage(sitk_image), expected))
            metadata = widget.session.case.metadata
            check(key + ' SimpleITK spacing ' + name, np.allclose(sitk_image.GetSpacing(), metadata['spacing_xyz_mm'], atol=1e-5))
            check(key + ' SimpleITK LPS origin ' + name, np.allclose(sitk_image.GetOrigin(), metadata['origin_lps_mm'], atol=1e-4))
            check(key + ' SimpleITK LPS direction ' + name, np.allclose(np.array(sitk_image.GetDirection()).reshape(3,3), metadata['direction_lps_columns'], atol=1e-5))
        independently_loaded_seg = slicer.util.loadSegmentation(str(checkpoint / 'segmentation.seg.nrrd'))
        for segment_id, expected in [('medial', saved_labels == 1), ('lateral', saved_labels == 2), ('uncertain', saved_uncertain > 0)]:
            reopened_segment = slicer.util.arrayFromSegmentBinaryLabelmap(independently_loaded_seg, segment_id, widget.volume)
            check(key + ' editable segmentation reopen ' + segment_id, np.array_equal(reopened_segment > 0, expected))
        slicer.mrmlScene.RemoveNode(independently_loaded_seg)
        widget.closeCase()
        widget.openCase(key)
        widget.goSlice(k)
        events()
        reopened_labels, reopened_uncertain = widget.collectArrays()
        check(key + ' save reopen labels', np.array_equal(saved_labels, reopened_labels))
        check(key + ' save reopen uncertainty', np.array_equal(saved_uncertain, reopened_uncertain))
        check(key + ' original dimensions retained', widget.volume.GetImageData().GetDimensions() == dims)
        check(key + ' incomplete review blocks approval', bool(widget.session.approval_errors(reopened_labels, reopened_uncertain, practice=True)))
        # Resolve uncertainty through actual Erase, then review the synthetic slices.
        stroke(widget, (i, j, k), tool='Erase', label='uncertain')
        resolved_labels, resolved_uncertain = widget.collectArrays()
        check(key + ' uncertainty erased separately', not resolved_uncertain.any())
        for row in widget.session.state['review']:
            row['reviewed'] = True
            row['flag'] = False
        widget.session.state['compartments'] = {'medial': True, 'lateral': True}
        widget.refreshReview()
        check(key + ' draft protocol blocks research approval', bool(widget.session.approval_errors(resolved_labels, resolved_uncertain, practice=False)))
        widget.save(approve=True, practice=True)
        approved_checkpoint = widget.session.current_checkpoint
        approved_arrays[key] = (resolved_labels.copy(), resolved_uncertain.copy())
        check(key + ' practice approval records honest automated role', widget.session.state['status'] == 'practice_approved' and widget.session.state['annotator'] == 'Software QA (automated)' and widget.session.state['approval']['human_anatomical_approval'] is False and widget.session.state['approval']['accepted_research_annotation'] is False)
        stroke(widget, (i+8, j+4, k), label='medial')
        widget.save()
        check(key + ' approved editing creates draft', widget.session.state['status'] == 'needs_review' and widget.session.current_checkpoint != approved_checkpoint)
        check(key + ' approved checkpoint preserved', approved_checkpoint.is_dir())
    widget.closeCase()
    exported = export_approved(widget.store, OUTPUT / 'Results 空間', include_practice=True)
    with zipfile.ZipFile(exported) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('practice ZIP explicitly marked', manifest['practice_only'] is True and exported.name.startswith('SOFTWARE_PRACTICE_ONLY-'))
        check('all approved synthetic cases exported', len(manifest['cases']) == len(keys))
        check('MRI images not duplicated in results', not any(n.endswith('/image.nii.gz') for n in archive.namelist()))
        check('export ZIP CRC integrity', archive.testzip() is None)
        for case in manifest['cases']:
            for name in ['labels.nii.gz', 'uncertainty.nii.gz', 'validity.nii.gz', 'slice_review.csv', 'segmentation.seg.nrrd']:
                check('export retains ' + name, case['folder'] + '/' + name in archive.namelist())
            for name, expected in zip(('labels.nii.gz', 'uncertainty.nii.gz'), approved_arrays[case['case_key']]):
                extracted = OUTPUT / ('verify-export-' + name)
                extracted.write_bytes(archive.read(case['folder'] + '/' + name))
                independent = nib.load(str(extracted))
                check(case['case_key'] + ' exported approved voxels ' + name, np.array_equal(np.asarray(independent.dataobj).transpose(2, 1, 0), expected))
                extracted.unlink()
    check('entire source package unchanged', source_hashes == {str(p.relative_to(dataset_root)): sha256(p) for p in dataset_root.rglob('*') if p.is_file()})
    # Verified correction initialization is explicit and uses a separate local job.
    original_store = widget.store
    correction_case = widget.dataset.cases[-1]
    starting = np.zeros(correction_case.shape_xyz[::-1], dtype=np.uint8)
    starting[3,20:24,30:34] = 1
    starting[5,30:34,40:44] = 2
    initialization_root = OUTPUT / 'Synthetic initialization'
    initialization_root.mkdir()
    starting_path = initialization_root / 'verified-start.nii.gz'
    write_native(starting_path, starting, correction_case)
    starting_digest = sha256(starting_path)
    explicit_job = {'schema_version':'meniscus_job/1', 'dataset_identity':widget.dataset.identity,
                    'protocol':{'version':'synthetic-correction-practice-1','status':'draft'},
                    'practice_context': software_context,
                    'cases':{correction_case.key:{'annotation_mode':'correction',
                    'starting_mask':{'path':str(starting_path),'sha256':starting_digest,
                                     'version':'synthetic-start-v1','source':'Committed synthetic integration generator'}}}}
    widget.store = WorkStore(OUTPUT / 'Correction work', widget.dataset, job=explicit_job)
    widget.openCase(correction_case.key)
    events()
    correction_labels, correction_uncertainty = widget.collectArrays()
    check('actual application loads explicitly permitted correction mask', np.array_equal(correction_labels,starting) and not correction_uncertainty.any())
    initialization = widget.session.state['initialization']
    check('correction source and version recorded', initialization['method']=='correction' and initialization['starting_mask']['sha256']==starting_digest and initialization['starting_mask']['version']=='synthetic-start-v1')
    preserved_start = widget.session.folder / ('starting-mask-' + starting_digest + '.nii.gz')
    check('correction original prediction preserved separately', preserved_start.is_file() and sha256(preserved_start)==starting_digest)
    widget.save()
    widget.closeCase()
    widget.openCase(correction_case.key)
    events()
    reopened_correction, reopened_uncertainty = widget.collectArrays()
    check('correction saves and reopens exact starting voxels', np.array_equal(reopened_correction,starting) and not reopened_uncertainty.any())
    widget.closeCase()
    widget.store = original_store
    check('correction does not alter original supplied mask', sha256(starting_path)==starting_digest and sha256(preserved_start)==starting_digest)
    check('correction leaves source package unchanged', source_hashes == {str(p.relative_to(dataset_root)): sha256(p) for p in dataset_root.rglob('*') if p.is_file()})
    widget.openCase(keys[-1])
    widget.goSlice(widget.session.case.n_slices // 2)
    node_count_before = slicer.mrmlScene.GetNumberOfNodes()
    for repeat in range(3):
        widget.save()
        events()
    check('repeated save does not accumulate scene helper nodes', slicer.mrmlScene.GetNumberOfNodes() == node_count_before, '%s -> %s' % (node_count_before,slicer.mrmlScene.GetNumberOfNodes()))
    # A failed save must abort case switching and retain the active unsaved case.
    from MeniscusAnnotatorLib.core import ValidationError
    original_session = widget.session
    original_save = original_session.save
    old_notes = str(widget.notes.toPlainText())
    widget.notes.setPlainText('Synthetic save-failure probe')
    def simulated_full_disk(*args, **kwargs):
        raise ValidationError('Synthetic insufficient disk space; free space and retry.')
    original_session.save = simulated_full_disk
    failed_as_expected = False
    try:
        widget.openCase(keys[0])
    except ValidationError:
        failed_as_expected = True
    finally:
        original_session.save = original_save
    check('save failure blocks case switch and retains unsaved work', failed_as_expected and widget.session is original_session and widget.dirty and not original_session.closed)
    widget.notes.setPlainText(old_notes)
    widget.save()
    # Close immediately after a native stroke, before the queued edit observer runs.
    dims = widget.volume.GetImageData().GetDimensions()
    target = (dims[0]//2+15, dims[1]//2+10, dims[2]//2)
    stroke(widget, target, flush=False)
    check('completed stroke awaits queued observer before immediate close', widget._editQueued and not widget.dirty)
    closing_case = widget.session.case
    widget.closeCase()
    latest = widget.store._checkpoints(widget.store.case_folder(closing_case))[0]
    close_labels = np.asarray(nib.load(str(latest / 'labels.nii.gz')).dataobj).transpose(2,1,0)
    check('immediate case close flushes and saves queued stroke', close_labels[target[2],target[1],target[0]] == 1)
    original_load = slicer.util.loadVolume
    slicer.util.loadVolume = lambda *args, **kwargs: None
    load_failed_as_expected = False
    try:
        widget.openCase(closing_case.key)
    except ValidationError:
        load_failed_as_expected = True
    finally:
        slicer.util.loadVolume = original_load
    check('failed native image load releases partial case session', load_failed_as_expected and widget.session is None and widget.volume is None)
    widget.openCase(closing_case.key)
    check('failed native image load releases writer lock for retry', widget.session is not None)
    widget.goSlice(target[2])
    events()
    case_state = (widget.session.case.key,widget.currentSlice,widget.activeLabel,widget.editor.activeEffect().name)
    canvas = slicer.app.layoutManager().sliceWidget('Red').sliceView()
    canvas_width = canvas.width
    widget.caseListDock.setVisible(False)
    widget.rightDock.setVisible(False)
    events()
    check('both side panels collapse', not widget.caseListDock.isVisible() and not widget.rightDock.isVisible())
    check('collapsed panels enlarge MRI canvas', canvas.width > canvas_width, '%s -> %s' % (canvas_width,canvas.width))
    check('slice controls remain visible when panels collapse', widget.sliceSlider.isVisible() and widget.sliceReadout.isVisible())
    widget.caseListDock.setVisible(True)
    widget.rightDock.setVisible(True)
    events()
    check('both side panels restore', widget.caseListDock.isVisible() and widget.rightDock.isVisible())
    check('panel toggles preserve annotation context', case_state == (widget.session.case.key,widget.currentSlice,widget.activeLabel,widget.editor.activeEffect().name))
    table = widget.caseTable
    REPORT['case_table'] = {'row_count':table.rowCount, 'column_count':table.columnCount, 'visible':table.isVisible(), 'header_visible':table.horizontalHeader().isVisible(), 'query':str(widget.search.text), 'filter':str(widget.progressFilter.currentText), 'rows':[{'hidden':table.isRowHidden(row),'identity':str(table.item(row,0).text()),'status':str(table.item(row,1).text())} for row in range(table.rowCount)]}
    check('case list populated and visible', table.isVisible() and table.rowCount == len(keys) and all(not table.isRowHidden(row) for row in range(table.rowCount)))
    table.grab().save(str(OUTPUT / 'synthetic-case-table.png'))
    table.viewport().update()
    table.horizontalHeader().repaint()
    table.repaint()
    events()
    window = slicer.util.mainWindow()
    REPORT['display'] = {'device_pixel_ratio': window.devicePixelRatioF(), 'captures': []}
    for width, height in [(1280, 800), (1440, 900)]:
        window.resize(width, height)
        events()
        slicer.app.layoutManager().sliceWidget('Red').sliceView().forceRender()
        check('slice slider visible at %dx%d' % (width,height), widget.sliceSlider.isVisible() and widget.sliceSlider.width >= 100)
        check('slice readout fits at %dx%d' % (width,height), widget.sliceReadout.isVisible() and widget.sliceReadout.width >= widget.sliceReadout.minimumSizeHint.width())
        screenshot = 'synthetic-application-%dx%d.png' % (width, height)
        window.grab().save(str(OUTPUT / screenshot))
        REPORT['display']['captures'].append({'requested_logical_size': [width, height], 'actual_logical_size': [window.width, window.height], 'file': screenshot})
    REPORT['screenshot'] = REPORT['display']['captures'][0]['file']
    if os.environ.get('MENISCUS_TEST_CLOSE_WINDOW') == '1':
        widget.notes.setPlainText('Synthetic close persistence probe')
        case = widget.session.case
        events()
        check('closing probe is dirty before window close', widget.dirty)
        window.close()
        events()
        check('actual window close releases case session', widget.session is None)
        latest = widget.store._checkpoints(widget.store.case_folder(case))[0]
        state = json.loads((latest / 'annotation.json').read_text())
        check('actual window close saves latest notes', state['notes'] == 'Synthetic close persistence probe')
    elif os.environ.get('MENISCUS_TEST_KEEP_OPEN') != '1':
        widget.closeCase()
    REPORT['passed'] = all(c['passed'] for c in REPORT['checks'])


try:
    run()
except Exception:
    REPORT['passed'] = False
    REPORT['error'] = traceback.format_exc()
    print(REPORT['error'])
    try:
        events()
        slicer.util.mainWindow().grab().save(str(OUTPUT / 'failure-application.png'))
        REPORT['failure_screenshot'] = 'failure-application.png'
    except Exception:
        pass
finally:
    (OUTPUT / 'slicer-workflow.json').write_text(json.dumps(REPORT, indent=2) + '\n')
    print('MENISCUS_TEST_REPORT=' + str(OUTPUT / 'slicer-workflow.json'))
    if os.environ.get('MENISCUS_TEST_KEEP_OPEN') != '1':
        slicer.app.exit(0 if REPORT.get('passed') else 1)
