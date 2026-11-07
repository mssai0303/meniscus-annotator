"""Development entry point: open the real Meniscus Annotator workspace directly."""
import os
import qt
import slicer

def start():
    slicer.app.userSettings().setValue('Modules/HomeModule','MeniscusAnnotator')
    slicer.util.selectModule('MeniscusAnnotator')
    widget = slicer.modules.meniscusannotator.widgetRepresentation().self()
    if os.environ.get('MENISCUS_DEMO_DATASET'):
        widget.openDataset(os.environ['MENISCUS_DEMO_DATASET'], work_root=os.environ.get('MENISCUS_DEMO_WORK'))
        widget.openCase(widget.dataset.cases[0].key)
    slicer.util.mainWindow().show()

qt.QTimer.singleShot(0,start)
