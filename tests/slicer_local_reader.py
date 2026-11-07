"""Actual local-reader dialogs and persistence using generated phantoms only.

Set MENISCUS_READER_TEST_OUTPUT to a new folder, then run phases edit and cold
in separate Slicer processes. No user settings or participant data are opened.
"""
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np
import qt
import slicer

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / 'tests')]
from MeniscusAnnotatorLib.core import Dataset, canonical, sha256, write_native
from MeniscusAnnotatorLib.reader_workspace import reader_workspace
from slicer_export_dialog import drive_export_dialog
from tools.make_synthetic import make_synthetic

OUTPUT = Path(os.environ['MENISCUS_READER_TEST_OUTPUT']).resolve()
PHASE = os.environ.get('MENISCUS_READER_TEST_PHASE', 'edit')
if PHASE == 'edit':
    OUTPUT.mkdir(parents=True, exist_ok=False)
elif PHASE != 'cold' or not OUTPUT.is_dir():
    raise ValueError('Reader test requires a new edit directory or existing cold directory.')
os.environ['MENISCUS_SETTINGS_FILE'] = str(OUTPUT / 'reader-settings.ini')
os.environ.pop('MENISCUS_SOFTWARE_PRACTICE_CONFIG', None)
os.environ.pop('MENISCUS_REAL_PRACTICE_CONFIG', None)
REPORT = {'phase': PHASE, 'platform': platform.platform(),
          'scope': 'Synthetic automated Qt dialog and persistence checks; not human or Windows acceptance.',
          'checks': [], 'slicer_version': slicer.app.applicationVersion}


def check(name, condition):
    REPORT['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def choose_reader(callback, reader=None):
    state = {'seen': False, 'error': None}
    timer = qt.QTimer()
    timer.setInterval(100)
    started = time.monotonic()

    def tick():
        modal = qt.QApplication.activeModalWidget()
        try:
            if time.monotonic() - started > 20:
                raise AssertionError('Reader prompt timed out')
            if modal is None:
                return
            if str(modal.objectName) != 'MeniscusReaderIdentityDialog':
                raise AssertionError('Unexpected dialog: ' + str(modal.windowTitle))
            entry = modal.findChild(qt.QLineEdit, 'MeniscusReaderIdentityInput')
            proceed = modal.findChild(qt.QPushButton, 'MeniscusReaderIdentityContinue')
            check('Reader name/ID dialog is visible', bool(entry and entry.isVisible() and proceed.isVisible()))
            entry.setText('   ')
            check('Blank reader cannot continue', not proceed.enabled)
            state['seen'] = True
            timer.stop()
            if reader is None:
                modal.reject()
                return
            entry.setText(reader)
            check('Explicit reader enables Continue', proceed.enabled)
            modal.grab().save(str(OUTPUT / ('reader-dialog-' + PHASE + '.png')))
            proceed.click()
        except Exception:
            state['error'] = traceback.format_exc()
            timer.stop()
            if modal:
                modal.reject()

    timer.connect('timeout()', tick)
    timer.start()
    try:
        result = callback()
    finally:
        timer.stop()
    if state['error']:
        raise AssertionError(state['error'])
    check('Reader prompt was shown', state['seen'])
    return result


widget = None
try:
    source = OUTPUT / 'Synthetic correction dataset'
    if PHASE == 'edit':
        make_synthetic(source, layout='flat')
        dataset = Dataset(source)
        job = {'schema_version': 'meniscus_job/1', 'dataset_identity': dataset.identity,
               'protocol': {'version': 'SYNTHETIC-READER-DRAFT-1', 'status': 'draft'}, 'cases': {}}
        for case in dataset.cases:
            labels = np.zeros(case.shape_xyz[::-1], dtype=np.uint8)
            labels[4, 12:14, 15:17] = 1
            labels[6, 18:20, 25:27] = 2
            mask = case.folder / 'starting_mask.nii.gz'
            write_native(mask, labels, case)
            job['cases'][case.key] = {'annotation_mode': 'correction', 'starting_mask': {
                'path': mask.relative_to(source).as_posix(), 'sha256': sha256(mask),
                'source': 'SYNTHETIC GEOMETRIC PHANTOM', 'version': 'SYNTHETIC-1'}}
        (source / 'correction_job.json').write_text(json.dumps(job))
        hashes = {str(p.relative_to(source)): sha256(p) for p in source.rglob('*') if p.is_file()}
        (OUTPUT / 'source-hashes.json').write_text(json.dumps(hashes))
    else:
        dataset = Dataset(source)
        job = json.loads((source / 'correction_job.json').read_text())
        hashes = json.loads((OUTPUT / 'source-hashes.json').read_text())
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    widget.settings = qt.QSettings(str(OUTPUT / 'reader-settings.ini'), qt.QSettings.IniFormat)
    reader_a, reader_b = 'SYNTHETIC Reader A', 'SYNTHETIC Reader B'
    plan_a = reader_workspace(dataset.version, job, reader=reader_a)
    plan_b = reader_workspace(dataset.version, job, reader=reader_b)
    work_a, work_b = OUTPUT / 'Reader A work', OUTPUT / 'Reader B work'
    widget.settings.setValue(plan_a['settings_key'], str(work_a))
    widget.settings.setValue(plan_b['settings_key'], str(work_b))
    case = dataset.cases[1]
    if PHASE == 'edit':
        cancelled = OUTPUT / 'Cancelled work'
        result = choose_reader(lambda: widget.openDataset(str(source), work_root=str(cancelled)))
        check('Cancel creates no work or reader binding', result is None and not cancelled.exists())
        choose_reader(lambda: widget.openDataset(str(source)), reader_a)
        widget.openCase(case.key)
        check('Chosen reader uses matching separate work', widget.store.root == work_a and widget.session.state['annotator'] == reader_a)
        check('Original job binding remains unchanged', widget.store.job_identity == canonical(job) and 'annotator' not in widget.store.job)
        medial = slicer.util.arrayFromSegmentBinaryLabelmap(widget.anatomy, 'medial', widget.volume)
        medial[5, 8, 9] = 1
        slicer.util.updateSegmentBinaryLabelmapFromArray(medial, widget.anatomy, 'medial', widget.volume)
        widget._segmentChanged()
        widget.notes.setPlainText('SYNTHETIC Reader A correction note')
        widget.goSlice(5)
        for row in widget.session.state['review']:
            row['reviewed'] = True
        widget.session.state['compartments'] = {'medial': True, 'lateral': True}
        widget.save(approve=True, practice=True)
        expected = widget.collectArrays()[0]
        np.save(OUTPUT / 'expected-labels.npy', expected)
        checkpoint = widget.session.current_checkpoint
        checkpoint_hashes = {p.name: sha256(p) for p in checkpoint.iterdir() if p.is_file()}
        choose_reader(lambda: widget.openDataset(str(source)), reader_b)
        widget.openCase(dataset.cases[0].key)
        check('Second reader has fresh separate attribution and notes', widget.store.root == work_b and widget.session.state['annotator'] == reader_b and not widget.session.state['notes'])
        widget.notes.setPlainText('SYNTHETIC Reader B note')
        widget.save()
        choose_reader(lambda: widget.openDataset(str(source)), reader_a)
        widget._resume()
        check('Returning reader resumes own last case', widget.session.case.key == case.key)
        check('Returning reader restores own notes and voxel edits', widget.session.state['notes'] == 'SYNTHETIC Reader A correction note' and np.array_equal(widget.collectArrays()[0], expected))
        check('Other reader never rewrites the earlier checkpoint', checkpoint_hashes == {p.name: sha256(p) for p in checkpoint.iterdir() if p.is_file()})
        drive_export_dialog(widget, OUTPUT / 'Results', action='export')
        check('Practice export completes through actual dialog', bool(widget._lastExport))
    else:
        choose_reader(widget._resume, reader_a)
        check('Fresh process resumes explicit reader and own case', widget.store.root == work_a and widget.session.state['annotator'] == reader_a and widget.session.case.key == case.key)
        check('Fresh process restores notes, slice and labels', widget.session.state['notes'] == 'SYNTHETIC Reader A correction note' and widget.currentSlice == 5 and np.array_equal(widget.collectArrays()[0], np.load(OUTPUT / 'expected-labels.npy')))
    check('Original dataset, masks and job stay byte-identical', hashes == {name: sha256(source / name) for name in hashes})
    widget.settings.sync()
    slicer.util.mainWindow().grab().save(str(OUTPUT / ('reader-workspace-' + PHASE + '.png')))
    REPORT['passed'] = True
except Exception:
    REPORT['passed'] = False
    REPORT['error'] = traceback.format_exc()
finally:
    if widget is not None:
        widget.dirty = False
        widget.closeCase()
    (OUTPUT / ('reader-' + PHASE + '.json')).write_text(json.dumps(REPORT, indent=2) + '\n')
    print('MENISCUS_LOCAL_READER_RESULT', json.dumps({'passed': REPORT.get('passed'), 'checks': len(REPORT['checks'])}), flush=True)
    slicer.app.exit(0 if REPORT.get('passed') else 1)
