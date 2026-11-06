"""Pinned Slicer shell controls; the annotation module owns its workspace."""
import qt
import slicer

_NATIVE_TOOLBARS = (
    'MainToolBar', 'ModuleToolBar', 'ModuleSelectorToolBar', 'UndoRedoToolBar',
    'ViewToolBar', 'MouseModeToolBar', 'ViewersToolBar', 'DialogToolBar', 'LayoutToolBar')

def focus_workflow_shell():
    """Hide only pinned Slicer shell controls; the module owns its workspace."""
    window = slicer.util.mainWindow()
    if window is None:
        return
    for name in _NATIVE_TOOLBARS:
        bar = window.findChild(qt.QToolBar, name)
        if bar is not None:
            bar.hide()
            for action in bar.actions():
                action.setShortcut(qt.QKeySequence())
    slicer.util.setPythonConsoleVisible(False)
    slicer.util.setErrorLogVisible(False)
    slicer.util.setApplicationLogoVisible(False)
    slicer.util.setModuleHelpSectionVisible(False)
    slicer.util.setModulePanelTitleVisible(False)
    slicer.util.setDataProbeVisible(False)
    # Keep upstream About/Qt/licence information available in Help.
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and menu.objectName in ('FileMenu', 'EditMenu', 'ViewMenu', 'LayoutMenu'):
            action.setVisible(False)
