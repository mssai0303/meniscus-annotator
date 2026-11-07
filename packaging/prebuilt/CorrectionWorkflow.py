"""Installed correction route on procedural cases; returns a detailed receipt.

Qt/VTK events are injected, not human input. Export drives the real dialog;
the native folder chooser is routed to an isolated generated output directory.
"""
import json
import platform
from pathlib import Path
import sys
import zipfile


def run(output, previous=None):
    import nibabel as nib
    import numpy as np
    import qt
    import slicer
    import vtk
    from MeniscusAnnotator import SOURCE_IDENTITY
    from MeniscusAnnotatorLib import core
    from make_correction_synthetic import make_correction_synthetic
    from tests.slicer_export_dialog import drive_export_dialog

    output = Path(output)
    original = Path(previous) if previous else output
    settings_root = original / 'Correction Qt settings'
    settings_root.mkdir(exist_ok=True)
    qt.QSettings.setDefaultFormat(qt.QSettings.IniFormat)
    qt.QSettings.setPath(qt.QSettings.IniFormat, qt.QSettings.UserScope, str(settings_root))
    report = {'schema_version': 'meniscus_synthetic_correction_workflow/1',
              'passed': False, 'platform': sys.platform, 'machine': platform.machine(),
              'slicer_version': slicer.app.applicationVersion,
              'slicer_revision': slicer.app.repositoryRevision, 'source_identity': SOURCE_IDENTITY, 'checks': [],
              'scope': 'Procedural correction cases, injected Qt/VTK events; not human acceptance or anatomy. Native export folder chooser is not tested.'}

    def check(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def events():
        slicer.app.processEvents()

    def stroke(widget, ijk, tool='Paint', label='medial'):
        widget.setLabel(label)
        widget.setTool(tool)
        effect = widget.editor.activeEffect()
        widget.brushSize.setValue(2.0)
        for name, value in [('BrushSphere', 0), ('EditIn3DViews', 0),
                            ('BrushDiameterIsRelative', 0), ('BrushAbsoluteDiameter', 2.0)]:
            effect.setParameter(name, value)
        red = slicer.app.layoutManager().sliceWidget('Red')
        matrix = vtk.vtkMatrix4x4()
        widget.volume.GetIJKToRASMatrix(matrix)
        world = matrix.MultiplyPoint([*ijk, 1])
        inverse = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(red.mrmlSliceNode().GetXYToRAS(), inverse)
        xy = inverse.MultiplyPoint(world)
        interactor = red.sliceView().interactorStyle().GetInteractor()
        interactor.SetEventInformation(int(round(xy[0])), int(round(xy[1])), 0, 0)
        for event in ('EnterEvent', 'MouseMoveEvent', 'LeftButtonPressEvent', 'LeftButtonReleaseEvent'):
            interactor.InvokeEvent(event)
        events()

    widget = None
    try:
        package = original / 'Synthetic correction dataset'
        work = original / 'Correction work'
        if not previous:
            make_correction_synthetic(package, automated=True)
        before = {p.relative_to(package).as_posix(): core.sha256(p) for p in package.rglob('*') if p.is_file()}
        slicer.util.selectModule('MeniscusAnnotator')
        widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
        widget.settings = qt.QSettings(str(settings_root / 'correction.ini'), qt.QSettings.IniFormat)
        widget.openDataset(str(package), work_root=str(work))
        events()
        check('ordinary open automatically loads package correction job', bool(widget.store.job))
        expected = json.loads((original / 'expected-correction.json').read_text(encoding='utf-8')) if previous else {}
        for case in widget.dataset.cases:
            widget.openCase(case.key)
            events()
            check(case.key + ' initializes correction mode', widget.session.state['initialization']['method'] == 'correction')
            check(case.key + ' has automated software actor', widget.session.state['annotator'] == core.PRACTICE_ACTORS['automated'])
            labels, uncertain = widget.collectArrays()
            if previous:
                wanted = expected[case.key]
                check(case.key + ' cold restart restores exact edited voxels', core.canonical(labels.tolist()) == wanted['labels'])
                check(case.key + ' cold restart restores exact uncertainty', core.canonical(uncertain.tolist()) == wanted['uncertainty'])
                check(case.key + ' cold restart restores review status', widget.session.state['review'] == wanted['review'])
                check(case.key + ' cold restart restores practice approval', widget.session.state['status'] == 'practice_approved')
                check(case.key + ' cold restart restores acquired slice', widget.currentSlice == wanted['slice'])
                widget.closeCase()
                continue
            start = np.asarray(nib.load(str(case.folder / 'starting_mask.nii.gz')).dataobj).transpose(2, 1, 0)
            check(case.key + ' loads exact starting voxels', np.array_equal(labels, start) and not uncertain.any())
            nx, ny, nz = case.shape_xyz
            i, j, k = nx // 2, ny // 2, nz // 2
            widget.goSlice(k)
            stroke(widget, (i, j, k))
            painted, _ = widget.collectArrays()
            check(case.key + ' paint changes only intended acquired plane', painted[k, j, i] == 1 and set(np.argwhere(painted != start)[:, 0]) == {k})
            widget._undo(); events()
            check(case.key + ' undo restores starting prediction', np.array_equal(widget.collectArrays()[0], start))
            widget._redo(); events()
            check(case.key + ' redo restores correction', np.array_equal(widget.collectArrays()[0], painted))
            stroke(widget, (i, j, k), tool='Erase')
            check(case.key + ' erase removes corrected voxel', widget.collectArrays()[0][k, j, i] == 0)
            widget._undo(); events()
            corrected, uncertain = widget.collectArrays()
            widget.save()
            checkpoint = widget.session.current_checkpoint
            check(case.key + ' checkpoint records loaded source identity', widget.session.state['runtime']['application_source_sha256'] == SOURCE_IDENTITY['application_source_sha256'])
            saved = nib.load(str(checkpoint / 'labels.nii.gz'))
            check(case.key + ' saved correction keeps physical grid', saved.shape == case.shape_xyz and np.allclose(saved.affine, case.affine_ras, atol=1e-5))
            widget.closeCase(); widget.openCase(case.key); events()
            check(case.key + ' reopen restores corrected arrays', np.array_equal(widget.collectArrays()[0], corrected))
            # These are automated software assertions, never a human anatomical approval.
            for row in widget.session.state['review']:
                row['reviewed'] = True
                row['flag'] = False
            widget.session.state['compartments'] = {'medial': True, 'lateral': True}
            widget.goSlice(k)
            widget.refreshReview()
            check(case.key + ' draft refuses research approval', bool(widget.session.approval_errors(corrected, uncertain, practice=False)))
            widget.save(approve=True, practice=True)
            check(case.key + ' only software practice approval recorded', widget.session.state['status'] == 'practice_approved' and not widget.session.state['approval']['accepted_research_annotation'])
            expected[case.key] = {'labels': core.canonical(corrected.tolist()), 'uncertainty': core.canonical(uncertain.tolist()),
                                  'review': widget.session.state['review'], 'slice': k}
            widget.closeCase()
        if not previous:
            (output / 'expected-correction.json').write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8')
            exports = output / 'Correction exports'
            report['cancel_dialog'] = drive_export_dialog(widget, exports, action='cancel')
            check('Cancel exports nothing', not list(exports.rglob('*.zip')))
            report['export_dialog'] = drive_export_dialog(widget, exports, action='export')
            archives = list(exports.rglob('*.zip'))
            check('real Export button produces one ZIP', len(archives) == 1)
            with zipfile.ZipFile(archives[0]) as archive:
                manifest = json.loads(archive.read('results.json'))
                check('results ZIP CRC verifies', archive.testzip() is None)
                check('results are practice-only', manifest.get('practice_only') is True and archives[0].name.startswith('SOFTWARE_PRACTICE_ONLY-'))
                check('both correction cases exported', len(manifest['cases']) == len(expected))
                for entry in manifest['cases']:
                    target = output / 'export-verification.nii.gz'
                    target.write_bytes(archive.read(entry['folder'] + '/labels.nii.gz'))
                    values = np.asarray(nib.load(str(target)).dataobj).transpose(2, 1, 0)
                    check(entry['case_key'] + ' exported arrays match approved correction', core.canonical(values.tolist()) == expected[entry['case_key']]['labels'])
                    target.unlink()
        check('source images, masks, job and review inputs stay byte-identical', before == {p.relative_to(package).as_posix(): core.sha256(p) for p in package.rglob('*') if p.is_file()})
        report['passed'] = True
    finally:
        (output / 'correction-workflow.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if widget and widget.session and not widget.dirty:
            widget.closeCase()
    return report
