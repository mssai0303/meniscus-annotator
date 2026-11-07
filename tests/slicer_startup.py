"""Inspect direct startup without selecting the module or loading a dataset.

Launch using the real application startup path/Bootstrap, adding this script
only as a delayed observer. A launch that needs selectModule is a failed test.
"""
import json
import os
from pathlib import Path
import platform
import re
import tempfile
import traceback
import qt
import slicer

OUTPUT = Path(os.environ.get('MENISCUS_STARTUP_OUTPUT', tempfile.mkdtemp(prefix='meniscus-startup-')))
OUTPUT.mkdir(parents=True, exist_ok=True)
REPORT = {'scope': 'Direct application startup inspection; no dataset, anatomy or installed-Windows claim.',
          'platform': platform.platform(), 'checks': []}


def check(name, condition, detail=''):
    REPORT['checks'].append({'name':name, 'passed':bool(condition), 'detail':detail})


def inspect():
    try:
        window = slicer.util.mainWindow()
        check('startup selects Meniscus Annotator directly', slicer.util.selectedModule() == 'MeniscusAnnotator', str(slicer.util.selectedModule()))
        check('startup window identifies Meniscus Annotator', str(window.windowTitle).startswith('Meniscus Annotator'), str(window.windowTitle))
        labels = [re.sub('<[^>]+>', '', str(label.text)).strip() for label in window.findChildren(qt.QLabel) if label.isVisible()]
        check('startup header identifies Meniscus Annotator', 'Meniscus Annotator' in labels)
        bars = [str(bar.objectName) for bar in window.findChildren(qt.QToolBar) if bar.isVisible()]
        check('startup hides unrelated Slicer toolbars', all(name.startswith('Meniscus') for name in bars), str(bars))
        check('startup has not loaded an MRI or prediction', slicer.mrmlScene.GetNodesByClass('vtkMRMLScalarVolumeNode').GetNumberOfItems() == 0)
        window.grab().save(str(OUTPUT / 'actual-startup.png'))
        REPORT['passed'] = all(c['passed'] for c in REPORT['checks'])
    except Exception:
        REPORT['passed'] = False
        REPORT['error'] = traceback.format_exc()
    finally:
        (OUTPUT / 'startup.json').write_text(json.dumps(REPORT, indent=2)+'\n', encoding='utf-8')
        print('MENISCUS_STARTUP_REPORT=' + str(OUTPUT / 'startup.json'), flush=True)
        if os.environ.get('MENISCUS_TEST_KEEP_OPEN') != '1':
            slicer.app.exit(0 if REPORT.get('passed') else 1)


qt.QTimer.singleShot(1500, inspect)
