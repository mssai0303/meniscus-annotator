"""Installed focused workflow. No downloads and no source-data access at launch."""
import os
import json
import traceback
from pathlib import Path
import runpy
import qt
import slicer

def focus_workflow_shell():
    root = Path(os.environ['SLICERRC']).resolve().parent
    runpy.run_path(str(root / 'WorkflowShell.py'))['focus_workflow_shell']()

def start():
    try:
        if os.environ.get('MENISCUS_PACKAGE_CHECK'):
            runpy.run_path(str(Path(os.environ['SLICERRC']).with_name('RuntimeCheck.py')), run_name='__main__')
            return
        # These methods/settings are from the pinned Slicer source, not guessed keys.
        settings = slicer.app.userSettings()
        settings.setValue('Modules/HomeModule', 'MeniscusAnnotator')
        settings.setValue('Extensions/AutoUpdateCheck', False)
        settings.setValue('Extensions/AutoUpdateInstall', False)
        settings.setValue('ApplicationUpdate/AutoUpdateCheck', False)
        settings.setValue('ApplicationUpdates/Enabled', False)
        focus_workflow_shell()
        slicer.util.selectModule('MeniscusAnnotator')
        focus_workflow_shell()
        window = slicer.util.mainWindow()
        window.setWindowTitle('Meniscus Annotator 0.2.0 | 3D Slicer 5.12.4')
        qt.QTimer.singleShot(0, focus_workflow_shell)
    except Exception:
        if os.environ.get('MENISCUS_PACKAGE_CHECK'):
            try:
                Path(os.environ['MENISCUS_PACKAGE_CHECK']).write_text(json.dumps({'passed': False, 'error': traceback.format_exc()}), encoding='utf-8')
            finally:
                slicer.app.exit(1)
            return
        slicer.util.errorDisplay('The annotation workflow could not start. Reinstall this fixed application version or contact the study maintainer. Your saved work is outside the installation folder.')
qt.QTimer.singleShot(0, start)
