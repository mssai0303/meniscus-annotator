"""Installed synthetic-only software checks. Never discovers MRI inputs."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import runpy
import sys
import traceback
import uuid

import qt
import slicer

INSTALL = Path(os.environ['SLICERRC']).resolve().parents[1]
KIT = INSTALL / 'TestKit'
ROOT = Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.GenericDataLocation)) / 'Meniscus Annotator synthetic tests'
STATE = ROOT / 'last-workflow.json'
ACTIONS = {'workflow', 'resume', 'create'}


def text_file(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def checked_run_id(value):
    if not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('Invalid synthetic test run identifier.')
    return value


def installed_modules():
    # TestKit contains helpers only, so no source checkout can shadow the application.
    expected = (INSTALL / 'lib' / 'Slicer-5.12' / 'qt-scripted-modules').resolve()
    import MeniscusAnnotator
    import MeniscusAnnotatorLib
    for module in (MeniscusAnnotator, MeniscusAnnotatorLib):
        if not Path(module.__file__).resolve().is_relative_to(expected):
            raise RuntimeError('Synthetic checks must load the installed application module.')
    return {'application_module': str(Path(MeniscusAnnotator.__file__).resolve()),
            'core_module': str(Path(MeniscusAnnotatorLib.__file__).resolve()),
            'application_version': MeniscusAnnotatorLib.APP_VERSION}


def source_helpers():
    # This single whitelisted helper package contains no application implementation.
    sys.path.insert(0, str(KIT))
    from tools.make_synthetic import make_synthetic
    if not Path(sys.modules['tools.make_synthetic'].__file__).resolve().is_relative_to(KIT):
        raise RuntimeError('Unexpected synthetic helper import.')
    return make_synthetic


def finish(message, output, passed):
    if os.environ.get('MENISCUS_TEST_AUTOCLOSE') != '1':
        box = qt.QMessageBox()
        box.setWindowTitle('Meniscus Annotator — synthetic software checks')
        box.setIcon(qt.QMessageBox.Information if passed else qt.QMessageBox.Warning)
        box.setText(message)
        box.setInformativeText('Results: ' + str(output) + '\nSynthetic geometric data only; these checks do not establish anatomical correctness.')
        open_button = box.addButton('Open results folder', qt.QMessageBox.ActionRole)
        box.addButton(qt.QMessageBox.Close)
        box.exec_()
        if box.clickedButton() == open_button:
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(output)))
    slicer.app.exit(0 if passed else 1)


def start():
    output = None
    receipt = {'schema_version': 'meniscus_installed_synthetic_checks/1', 'passed': False,
               'scope': 'Installed application, procedural synthetic inputs only; no participant MRI is located or loaded.'}
    try:
        action = os.environ.get('MENISCUS_TEST_ACTION', 'workflow')
        if action not in ACTIONS:
            raise ValueError('Unsupported synthetic test action.')
        run_id = checked_run_id(os.environ.get('MENISCUS_TEST_RUN_ID', uuid.uuid4().hex))
        ROOT.mkdir(parents=True, exist_ok=True)
        output = ROOT / run_id
        output.mkdir(exist_ok=False)
        receipt.update(action=action, run_id=run_id, created_utc=dt.datetime.now(dt.timezone.utc).isoformat(), **installed_modules())
        # Test executables use a separate Qt application name/profile. The suite
        # further redirects its widget settings into these generated directories.
        if slicer.app.applicationName != 'MeniscusAnnotatorTest':
            raise RuntimeError('Synthetic checks require their isolated test launcher/profile.')
        for key in ('MENISCUS_TEST_OUTPUT', 'MENISCUS_RESUME_FROM', 'MENISCUS_TEST_KEEP_OPEN', 'MENISCUS_TEST_CLOSE_WINDOW', 'MENISCUS_TEST_LAYOUT'):
            os.environ.pop(key, None)
        make_synthetic = source_helpers()
        if action == 'create':
            package = output / 'Synthetic practice dataset'
            make_synthetic(package, layout='flat')
            from MeniscusAnnotatorLib import Dataset
            dataset = Dataset(package)
            if not dataset.cases or any(not c.key.startswith('SYNTHETIC_') for c in dataset.cases):
                raise RuntimeError('Generated package is not the expected synthetic fixture.')
            receipt.update(passed=True, package=str(package), cases=len(dataset.cases), folder_layout='flat')
            text_file(output / 'installed-tests.json', receipt)
            finish('Synthetic practice package created. Open the normal Meniscus Annotator application and choose this package with Open dataset.', package, True)
            return
        if action == 'resume':
            previous = json.loads(STATE.read_text(encoding='utf-8'))
            previous_id = checked_run_id(previous['run_id'])
            previous_root = ROOT / previous_id
            marker = json.loads((previous_root / 'installed-tests.json').read_text(encoding='utf-8'))
            if marker.get('action') != 'workflow' or not marker.get('passed') or marker.get('run_id') != previous_id:
                raise ValueError('No completed synthetic workflow is available for a restart check.')
            os.environ['MENISCUS_RESUME_FROM'] = str(previous_root)
        os.environ['MENISCUS_TEST_OUTPUT'] = str(output)
        os.environ['MENISCUS_TEST_LAYOUT'] = 'flat'
        os.environ['MENISCUS_TEST_KEEP_OPEN'] = '1'
        os.environ['MENISCUS_TEST_CLOSE_WINDOW'] = '1'
        # Preserve the suite's actual main-window close/save check, then show a
        # separate result dialog after the native workspace has closed.
        qt.QApplication.setQuitOnLastWindowClosed(False)
        runpy.run_path(str(INSTALL / 'WorkflowShell.py'))['focus_workflow_shell']()
        runpy.run_path(str(KIT / 'tests' / 'slicer_workflow.py'), run_name='__main__')
        report = json.loads((output / 'slicer-workflow.json').read_text(encoding='utf-8'))
        receipt.update(passed=bool(report.get('passed')), checks=len(report.get('checks', [])), report='slicer-workflow.json')
        text_file(output / 'installed-tests.json', receipt)
        if receipt['passed'] and action == 'workflow':
            text_file(STATE, {'run_id': run_id})
        finish(('Passed ' if receipt['passed'] else 'Failed during ') + str(receipt['checks']) + ' synthetic checks.', output, receipt['passed'])
    except Exception:
        receipt['error'] = traceback.format_exc()
        if output is not None:
            text_file(output / 'installed-tests.json', receipt)
        else:
            ROOT.mkdir(parents=True, exist_ok=True)
            output = ROOT
        finish('Synthetic checks could not complete. Open the result report for the affected check.', output, False)

qt.QTimer.singleShot(0, start)
