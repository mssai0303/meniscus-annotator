"""Actual modal Export controls, using synthetic correction fixtures only.

Run inside Slicer with --additional-module-paths pointing to the repository.
MENISCUS_EXPORT_TEST_OUTPUT must be a new directory outside the repository.
The import-safe helper is also used by the installed Windows test kit.

This drives Qt button/keyboard events in the application, not the export helper
directly. It does not certify human usability or test the native folder picker:
the existing practice destination mechanism supplies a fixed synthetic folder.
"""
import json
import copy
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
import zipfile

import numpy as np
import qt
import slicer


def drive_export_dialog(widget, output_dir, action='cancel', selected_only=False):
    """Operate the real modal dialog and return inspectable button evidence.

    output_dir is supplied through the application's existing practice export
    path, temporarily. Source/job, checkpoint and approval rules are unchanged.
    Callback errors close this test's modal dialog and are re-raised to caller.
    """
    if action not in ('cancel', 'export', 'escape', 'enter'):
        raise ValueError('Unsupported modal export action.')
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_config = widget._practiceConfig
    widget._practiceConfig = dict(previous_config or {}, results_root=str(output_dir))
    evidence = {'action': action, 'selected_only': bool(selected_only),
                'event_delivery': 'Actual Qt button click or key event; automated, not a human mouse run',
                'destination_scope': 'Fixed isolated practice destination; native folder picker not tested'}
    state = {'seen': False, 'completed': False, 'error': None}
    started = time.monotonic()
    timer = qt.QTimer()
    timer.setInterval(100)

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 20:
                raise AssertionError('Export dialog interaction timed out.')
            if modal is None:
                return
            if str(modal.objectName) == 'MeniscusExportDialog' and not state['seen']:
                state['seen'] = True
                boxes = modal.findChildren(qt.QDialogButtonBox)
                if len(boxes) != 1:
                    raise AssertionError('Expected one actual export button box.')
                box = boxes[0]
                ok = box.button(qt.QDialogButtonBox.Ok)
                cancel = box.button(qt.QDialogButtonBox.Cancel)
                evidence['buttons'] = [
                    {'role': role, 'present': button is not None,
                     'visible': bool(button and button.isVisible()),
                     'enabled': bool(button and button.enabled),
                     'text': str(button.text) if button else None}
                    for role, button in [('export', ok), ('cancel', cancel)]]
                if not all(item['present'] and item['visible'] and item['enabled'] for item in evidence['buttons']):
                    raise AssertionError('Both Export and Cancel must be visible and enabled.')
                choices = {str(c.objectName): c for c in modal.findChildren(qt.QCheckBox)}
                choices['MeniscusExportSelectedOnly'].setChecked(bool(selected_only))
                if not choices['MeniscusExportPractice'].checked:
                    choices['MeniscusExportPractice'].setChecked(True)
                modal.grab().save(str(output_dir / ('export-dialog-' + action + '.png')))
                if action in ('cancel', 'export'):
                    (cancel if action == 'cancel' else ok).click()
                else:
                    key = qt.Qt.Key_Escape if action == 'escape' else qt.Qt.Key_Return
                    modal.setFocus()
                    for kind in (qt.QEvent.KeyPress, qt.QEvent.KeyRelease):
                        qt.QApplication.sendEvent(modal, qt.QKeyEvent(kind, key, qt.Qt.NoModifier))
            elif str(modal.windowTitle) == 'Export complete':
                state['completed'] = True
                close = modal.button(qt.QMessageBox.Close)
                if close is None or not close.isVisible():
                    raise AssertionError('The completion notice needs a visible Close button.')
                close.click()
            elif state['seen'] and str(modal.objectName) != 'MeniscusExportDialog':
                raise AssertionError('Unexpected modal dialog during export: ' + str(modal.windowTitle))
        except Exception:
            state['error'] = traceback.format_exc()
            timer.stop()
            if modal is not None:
                modal.reject()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        widget._exportDialog()
    finally:
        timer.stop()
        widget._practiceConfig = previous_config
    if state['error']:
        raise AssertionError(state['error'])
    if not state['seen']:
        raise AssertionError('The application never showed its export dialog.')
    if state['completed'] != (action in ('export', 'enter')):
        raise AssertionError('Export completion did not match the requested action.')
    evidence['completion_notice'] = state['completed']
    return evidence


def drive_start_prompts(callback, decisions):
    """Answer actual startup confirmation dialogs, without invoking their slots."""
    remaining = list(decisions)
    seen = []
    errors = []
    started = time.monotonic()
    timer = qt.QTimer()
    timer.setInterval(100)

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 20:
                raise AssertionError('Dataset-start prompt timed out.')
            if modal is None:
                return
            if not remaining:
                raise AssertionError('Unexpected additional dataset-start prompt.')
            name, accepted = remaining.pop(0)
            if str(modal.objectName) != name:
                raise AssertionError('Unexpected dataset-start dialog: ' + str(modal.objectName))
            yes, no = modal.button(qt.QMessageBox.Yes), modal.button(qt.QMessageBox.No)
            if not yes or not no or not yes.isVisible() or not no.isVisible():
                raise AssertionError('Dataset-start prompt needs visible Yes and No.')
            if modal.defaultButton() != no:
                raise AssertionError('Dataset-start prompt must default to No.')
            seen.append({'dialog': name, 'accepted': bool(accepted), 'default_is_no': True,
                         'text': str(modal.text)})
            (yes if accepted else no).click()
        except Exception:
            errors.append(traceback.format_exc())
            timer.stop()
            if modal is not None:
                modal.reject()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        result = callback()
    finally:
        timer.stop()
    if errors or remaining:
        raise AssertionError('\n'.join(errors) if errors else 'Expected dataset-start prompt was absent.')
    return result, seen


def run_synthetic_export_test():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from tools.make_synthetic import make_synthetic
    from MeniscusAnnotatorLib.core import Dataset, sha256, write_native
    configured = os.environ.get('MENISCUS_EXPORT_TEST_OUTPUT')
    if not configured:
        raise ValueError('Set MENISCUS_EXPORT_TEST_OUTPUT to a new isolated local directory.')
    output = Path(configured).resolve()
    if output == repo or repo in output.parents or output.exists():
        raise ValueError('Export test output must be new and outside the source repository.')
    output.mkdir(parents=True)
    settings_root = output / 'Settings'
    settings_root.mkdir()
    qt.QSettings.setDefaultFormat(qt.QSettings.IniFormat)
    qt.QSettings.setPath(qt.QSettings.IniFormat, qt.QSettings.UserScope, str(settings_root))
    os.environ['MENISCUS_SETTINGS_FILE'] = str(settings_root / 'export-dialog.ini')
    os.environ.pop('MENISCUS_SOFTWARE_PRACTICE_CONFIG', None)
    os.environ.pop('MENISCUS_REAL_PRACTICE_CONFIG', None)
    report = {'scope': 'Automated actual-dialog regression using synthetic correction only; no human or Windows acceptance implied',
              'machine': platform.machine(), 'platform': platform.platform(),
              'slicer_version': slicer.app.applicationVersion,
              'slicer_revision': slicer.app.repositoryRevision,
              'module_sha256': sha256(repo / 'MeniscusAnnotator.py'), 'checks': [], 'dialogs': []}

    def check(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    widget = None
    try:
        source = make_synthetic(output / 'Synthetic correction sources', layout='flat')
        dataset = Dataset(source)
        job = {'schema_version': 'meniscus_job/1', 'dataset_identity': dataset.identity,
               'protocol': {'version': 'SYNTHETIC-EXPORT-DIALOG-1', 'status': 'draft'},
               'practice_context': {'purpose': 'software_practice', 'actor_type': 'automated', 'actor': 'Software QA (automated)'},
               'cases': {}}
        starts = {}
        for case in dataset.cases:
            values = np.zeros(case.shape_xyz[::-1], dtype=np.uint8)
            values[4, 12:14, 15:17] = 1
            values[6, 18:20, 25:27] = 2
            start = case.folder / 'starting_mask.nii.gz'
            write_native(start, values, case)
            starts[case.key] = values
            job['cases'][case.key] = {'annotation_mode': 'correction', 'starting_mask': {
                'path': start.relative_to(source).as_posix(), 'sha256': sha256(start),
                'source': 'SYNTHETIC GEOMETRIC PHANTOM; NOT PATIENT DATA', 'version': 'SYNTHETIC-1'}}
        (source / 'correction_job.json').write_text(json.dumps(job), encoding='utf-8')
        source_hashes = {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()}
        slicer.util.selectModule('MeniscusAnnotator')
        widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
        widget.settings = qt.QSettings(str(settings_root / 'export-dialog.ini'), qt.QSettings.IniFormat)
        widget.openDataset(str(source), work_root=str(output / 'Separate synthetic work'))
        for case in dataset.cases:
            widget.openCase(case.key)
            slicer.app.processEvents()
            labels, uncertain = widget.collectArrays()
            check(case.key + ' exact starting mask loaded', np.array_equal(labels, starts[case.key]) and not uncertain.any())
            for row in widget.session.state['review']:
                row['reviewed'] = True
                row['flag'] = False
            widget.session.state['compartments'] = {'medial': True, 'lateral': True}
            widget.save(approve=True, practice=True)
        results = output / 'Results'
        for action in ('cancel', 'escape'):
            report['dialogs'].append(drive_export_dialog(widget, results, action=action))
            check(action + ' creates no ZIP', not list(results.glob('*.zip')))
        report['dialogs'].append(drive_export_dialog(widget, results, action='export'))
        exports = list(results.glob('*.zip'))
        check('Export click creates one ZIP', len(exports) == 1)
        with zipfile.ZipFile(exports[0]) as archive:
            manifest = json.loads(archive.read('results.json'))
            check('Export click ZIP integrity', archive.testzip() is None)
            check('Export click includes both approved synthetic correction cases', len(manifest['cases']) == len(dataset.cases))
            check('Export stays software practice', manifest.get('practice_only') is True and manifest.get('accepted_research_annotation') is False)
            check('Export excludes MRI pixels', not any(name.endswith('/image.nii.gz') for name in archive.namelist()))
        widget.caseTable.selectRow(0)
        report['dialogs'].append(drive_export_dialog(widget, results, action='enter', selected_only=True))
        exports = list(results.glob('*.zip'))
        check('Return key creates a second ZIP', len(exports) == 2)
        with zipfile.ZipFile(widget._lastExport) as archive:
            manifest = json.loads(archive.read('results.json'))
            check('Selected-only Return export includes exactly selected case', [c['case_key'] for c in manifest['cases']] == [dataset.cases[0].key])
            check('Selected-only ZIP integrity', archive.testzip() is None)
        check('Synthetic input package is unchanged', source_hashes == {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob('*') if p.is_file()})
        # Check deliberate blank/reader decisions on fresh synthetic copies.
        # No real cases or research approvals are used for these UI checks.
        previous_dataset, previous_store = widget.dataset, widget.store
        blank_source = make_synthetic(output / 'MRI-only synthetic sources', layout='flat')
        blank_work = output / 'Declined blank work'
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(blank_source), work_root=str(blank_work)),
            [('MeniscusBlankStartDialog', False)])
        report['dataset_start_dialogs'] = evidence
        check('Declining blank start creates no work', result is None and not blank_work.exists())
        check('Declining blank start keeps prior dataset and work', widget.dataset is previous_dataset and widget.store is previous_store)
        ordinary_source = make_synthetic(output / 'Named-reader synthetic sources', layout='flat')
        ordinary_dataset = Dataset(ordinary_source)
        ordinary_job = copy.deepcopy(job)
        ordinary_job.pop('practice_context')
        ordinary_job['annotator'] = 'Synthetic reader confirmation probe'
        for case in ordinary_dataset.cases:
            path = case.folder / 'starting_mask.nii.gz'
            write_native(path, starts[case.key], case)
            ordinary_job['cases'][case.key]['starting_mask']['sha256'] = sha256(path)
        (ordinary_source / 'correction_job.json').write_text(json.dumps(ordinary_job), encoding='utf-8')
        ordinary_work = output / 'Named-reader synthetic work'
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(ordinary_source), work_root=str(ordinary_work)),
            [('MeniscusReaderConfirmDialog', False)])
        report['dataset_start_dialogs'].extend(evidence)
        check('Declining assigned reader creates no work', result is None and not ordinary_work.exists())
        check('Assigned reader prompt names explicit synthetic actor', ordinary_job['annotator'] in evidence[0]['text'])
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(ordinary_source), work_root=str(ordinary_work)),
            [('MeniscusReaderConfirmDialog', True)])
        report['dataset_start_dialogs'].extend(evidence)
        check('Confirming assigned reader opens correct dataset', result is not None and result.root == ordinary_source.resolve() and widget.store.root == ordinary_work.resolve())
        check('Opening named job creates no case annotation or approval', not list(ordinary_work.rglob('annotation.json')))
        # The normal remembered-work route must separate two readers of the same
        # dataset. No explicit work_root is passed; old version-only preferences
        # intentionally point somewhere else and must not be reused.
        from MeniscusAnnotatorLib.reader_workspace import reader_workspace
        version = ordinary_dataset.cases[0].metadata['dataset_version']
        plan_a = reader_workspace(version, ordinary_job)
        work_a = output / 'Remembered work for reader A'
        wrong_shared = output / 'Legacy shared work must stay unused'
        widget.settings.setValue(plan_a['settings_key'], str(work_a))
        widget.settings.setValue(plan_a['legacy_settings_key'], str(wrong_shared))
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(ordinary_source)),
            [('MeniscusReaderConfirmDialog', True)])
        report['dataset_start_dialogs'].extend(evidence)
        check('Reader A uses assigned remembered location without forced work_root', widget.store.root == work_a.resolve())
        check('Reader name stays visible in the case panel', ordinary_job['annotator'] in str(widget.datasetLabel.text))
        widget.openCase(ordinary_dataset.cases[0].key)
        widget.notes.setPlainText('SYNTHETIC reader A saved note')
        widget.save()
        saved_a = widget.session.current_checkpoint
        saved_a_hashes = {p.relative_to(saved_a).as_posix(): sha256(p) for p in saved_a.rglob('*') if p.is_file()}
        other_source = output / 'Second reader synthetic sources'
        shutil.copytree(ordinary_source, other_source)
        other_job = copy.deepcopy(ordinary_job)
        other_job['annotator'] = 'Synthetic reader B confirmation probe'
        (other_source / 'correction_job.json').write_text(json.dumps(other_job), encoding='utf-8')
        plan_b = reader_workspace(version, other_job)
        work_b = output / 'Remembered work for reader B'
        widget.settings.setValue(plan_b['settings_key'], str(work_b))
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(other_source)),
            [('MeniscusReaderConfirmDialog', True)])
        report['dataset_start_dialogs'].extend(evidence)
        check('Reader B uses a different assigned work location', widget.store.root == work_b.resolve() and work_a != work_b)
        widget.openCase(ordinary_dataset.cases[0].key)
        check('Reader B never inherits reader A note or attribution', widget.session.state['annotator'] == other_job['annotator'] and not widget.session.state['notes'])
        widget.notes.setPlainText('SYNTHETIC reader B saved note')
        widget.save()
        result, evidence = drive_start_prompts(
            lambda: widget.openDataset(str(ordinary_source)),
            [('MeniscusReaderConfirmDialog', True)])
        report['dataset_start_dialogs'].extend(evidence)
        widget.openCase(ordinary_dataset.cases[0].key)
        check('Returning to reader A restores only that assignment', widget.store.root == work_a.resolve() and widget.session.state['notes'] == 'SYNTHETIC reader A saved note' and widget.session.state['annotator'] == ordinary_job['annotator'])
        check('Reader A checkpoint remains unchanged after reader B work', saved_a_hashes == {p.relative_to(saved_a).as_posix(): sha256(p) for p in saved_a.rglob('*') if p.is_file()})
        check('Legacy shared work location was never created', not wrong_shared.exists())
        slicer.util.mainWindow().grab().save(str(output / 'named-reader-workspace.png'))
        report['passed'] = True
    except Exception:
        report['passed'] = False
        report['error'] = traceback.format_exc()
    finally:
        (output / 'export-dialog-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if widget is not None:
            widget.dirty = False
            widget.closeCase()
        print('MENISCUS_EXPORT_DIALOG_RESULT', json.dumps({'passed': report.get('passed', False), 'checks': len(report['checks']), 'report': str(output / 'export-dialog-report.json')}))
        slicer.app.exit(0 if report.get('passed') else 1)


if __name__ == '__main__':
    run_synthetic_export_test()
