"""Focused native-grid meniscus annotation workflow for Slicer 5.12.4."""
import json
import os
from pathlib import Path
import sys
import traceback

import numpy as np
import qt
import ctk
import vtk
import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget
from MeniscusAnnotatorLib import Dataset, WorkStore, ValidationError, export_approved

VERSION = '0.1.0'
LABELS = {'medial': ('Medial meniscus', (0.30, 0.78, 0.92)),
          'lateral': ('Lateral meniscus', (0.95, 0.64, 0.31)),
          'uncertain': ('Uncertain area', (0.76, 0.56, 0.88))}


class CloseGuard(qt.QObject):
    def __init__(self, workflow):
        super().__init__(slicer.util.mainWindow())
        self.workflow = workflow

    def eventFilter(self, watched, event):
        if event.type() == qt.QEvent.Close and self.workflow.dataset:
            try:
                # Complete storage while native modules still exist, before Qt teardown.
                self.workflow.closeCase()
            except Exception as exc:
                self.workflow._diagnostic = traceback.format_exc()
                slicer.util.errorDisplay('The case could not be saved. Check available disk space and work-folder permissions, then retry Save draft. The application will stay open.\n\n' + str(exc), windowTitle='Save required before closing')
                event.ignore()
                return True
            event.ignore()
            qt.QTimer.singleShot(0, lambda: slicer.app.exit(0))
            return True
        return False


class MeniscusAnnotator(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = 'Meniscus annotation'
        parent.categories = ['Annotation']
        parent.contributors = ['Meniscus Annotator contributors']
        parent.helpText = 'Open a dataset, annotate each acquired plane, review every slice, save and approve.'
        parent.acknowledgementText = 'Built on 3D Slicer. For research annotation.'


class MeniscusAnnotatorWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        super().setup()
        self.dataset = self.store = self.session = None
        self.volume = self.anatomy = self.uncertainty = None
        self.currentSlice = 0
        self.activeLabel = 'medial'
        self.dirty = False
        self._updating = False
        self._loading = False
        self._snap = False
        self._observers = []
        self._lastArrays = None
        self._editQueued = False
        self._lastExport = None
        self._diagnostic = ''
        self.settings = qt.QSettings()
        self._buildStyle()
        self._buildCases()
        self._buildEditor()
        self._buildBars()
        self.autosave = qt.QTimer()
        self.autosave.setInterval(60000)
        self.autosave.connect('timeout()', self._autosave)
        self.autosave.start()
        self.closeGuard = CloseGuard(self)
        slicer.util.mainWindow().installEventFilter(self.closeGuard)
        slicer.app.connect('aboutToQuit()', self._quit)
        self._enable(False)
        qt.QTimer.singleShot(0, self._finishLayout)

    def _buildStyle(self):
        families = list(qt.QFontDatabase().families())
        family = 'Segoe UI Variable' if 'Segoe UI Variable' in families else ('Segoe UI' if 'Segoe UI' in families else 'Arial')
        self.font = qt.QFont(family, 11)
        self.parent.setFont(self.font)
        self.style = '''
        QWidget { color:#25313c; font-size:11pt; font-weight:400; }
        ctkCollapsibleButton { background:#e6edf3; color:#25313c; border:1px solid #b8c2cc; border-radius:2px; padding:6px; text-align:left; }
        QToolBar { background:#edf1f4; border:0; spacing:5px; padding:4px; }
        QWidget#MeniscusCases { background:#f3f5f7; }
        QCheckBox::indicator { width:16px; height:16px; border:1px solid #8796a3; background:white; }
        QCheckBox::indicator:checked { background:#246a99; border:2px solid #1b557d; }
        QDockWidget, QWidget#annotationPanel { background:#f3f5f7; }
        QLabel#identity { font-size:14pt; font-weight:600; }
        QLabel#panelTitle { font-size:12pt; font-weight:600; padding-top:6px; }
        QLabel#support { color:#52616e; }
        QPushButton, QToolButton { min-height:28px; padding:3px 9px; border:1px solid #b8c2cc; border-radius:3px; background:#fafbfc; }
        QPushButton:hover, QToolButton:hover { background:#e6edf3; border-color:#8096a8; }
        QPushButton:checked, QToolButton:checked { background:#dcecf7; border:2px solid #246a99; }
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border:2px solid #246a99; }
        QPushButton:disabled { color:#7a8793; background:#ebeff2; border-color:#d6dde3; }
        QPushButton#primary { background:#246a99; color:white; border-color:#246a99; }
        QPushButton#primary:hover { background:#19577f; }
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:white; border:1px solid #b8c2cc; padding:5px; border-radius:2px; min-height:23px; }
        QTableWidget { background:white; border:1px solid #cbd3db; gridline-color:#e4e8ec; selection-background-color:#dcecf7; selection-color:#182c3c; }
        QHeaderView::section { background:#e9eef2; padding:7px; border:0; border-bottom:1px solid #cbd3db; font-weight:600; }
        QProgressBar { border:1px solid #c3cdd5; background:#e6ebef; text-align:center; min-height:20px; color:#25313c; }
        QProgressBar::chunk { background:#a7c6dc; }
        QCheckBox { spacing:7px; min-height:26px; }
        '''
        self.parent.setObjectName('MeniscusCases')
        self.parent.setAttribute(qt.Qt.WA_StyledBackground, True)
        self.parent.setAutoFillBackground(True)
        self.parent.setStyleSheet(self.style)

    def _title(self, text, layout):
        label = qt.QLabel(text)
        label.objectName = 'panelTitle'
        layout.addWidget(label)
        return label

    def _button(self, text, callback, layout, primary=False):
        b = qt.QPushButton(text)
        if primary:
            b.objectName = 'primary'
        b.connect('clicked()', callback)
        layout.addWidget(b)
        return b

    def _buildCases(self):
        self.layout.setContentsMargins(12, 8, 12, 10)
        self.layout.setSpacing(8)
        self._title('Cases', self.layout)
        self._button('Open dataset', self._chooseDataset, self.layout, True)
        self.resumeButton = self._button('Resume work', self._resume, self.layout)
        self.search = qt.QLineEdit()
        self.search.placeholderText = 'Search OAI ID, visit or side'
        self.search.connect('textChanged(QString)', self._filter)
        self.layout.addWidget(self.search)
        self.progressFilter = qt.QComboBox()
        self.progressFilter.addItems(['All cases', 'Not started', 'In progress', 'Needs review', 'Approved'])
        self.progressFilter.connect('currentIndexChanged(int)', self._filter)
        self.layout.addWidget(self.progressFilter)
        self.caseTable = qt.QTableWidget(0, 2)
        # Item delegates use the view palette; make text explicit under Slicer themes.
        tablePalette = self.caseTable.palette
        for role in [qt.QPalette.Text, qt.QPalette.WindowText, qt.QPalette.ButtonText]:
            tablePalette.setColor(role, qt.QColor('#25313c'))
        tablePalette.setColor(qt.QPalette.Base, qt.QColor('#ffffff'))
        self.caseTable.palette = tablePalette
        self.caseTable.horizontalHeader().palette = tablePalette
        self.caseTable.setStyleSheet('QTableWidget { color:#25313c; background:#ffffff; gridline-color:#dce3e9; } QHeaderView::section { color:#25313c; background:#e9eef2; border:0; padding:7px; }')
        self.caseTable.setHorizontalHeaderLabels(['OAI ID · visit · side', 'Progress'])
        self.caseTable.verticalHeader().hide()
        self.caseTable.horizontalHeader().setStretchLastSection(True)
        self.caseTable.setColumnWidth(0, 170)
        self.caseTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.caseTable.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.caseTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.caseTable.connect('cellDoubleClicked(int,int)', self._openRow)
        self.layout.addWidget(self.caseTable, 1)
        self._button('Open selected case', lambda: self._openRow(self.caseTable.currentRow(), 0), self.layout)
        self.datasetLabel = qt.QLabel('Choose the complete downloaded dataset folder.\nSource images remain read-only.')
        self.datasetLabel.wordWrap = True
        self.datasetLabel.objectName = 'support'
        self.layout.addWidget(self.datasetLabel)
        outputRow = qt.QHBoxLayout()
        self._button('Show saved files', self._showWork, outputRow)
        self._button('Export results', self._exportDialog, outputRow)
        self.layout.addLayout(outputRow)
        self._button('Load job configuration', self._loadJob, self.layout)
        self._button('Setup and shortcut help', self._help, self.layout)

    def _buildEditor(self):
        self.rightDock = qt.QDockWidget('Annotation', slicer.util.mainWindow())
        self.rightDock.objectName = 'MeniscusAnnotationTools'
        self.rightDock.setAllowedAreas(qt.Qt.RightDockWidgetArea | qt.Qt.LeftDockWidgetArea)
        panel = qt.QWidget()
        panel.objectName = 'annotationPanel'
        panel.setFont(self.font)
        panel.setStyleSheet(self.style)
        lay = qt.QVBoxLayout(panel)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(8)
        self._title('Anatomical label', lay)
        self.labelButtons = {}
        self.labelCombo = qt.QComboBox()
        for key in LABELS:
            name, color = LABELS[key]
            swatch = qt.QPixmap(16,16)
            swatch.fill(qt.QColor.fromRgbF(*color))
            self.labelCombo.addItem(qt.QIcon(swatch), name, key)
        self.labelCombo.connect('currentIndexChanged(int)', lambda index: self.setLabel(list(LABELS)[index]))
        lay.addWidget(self.labelCombo)
        self.toolText = qt.QLabel('Medial meniscus · Paint · 3 mm')
        self.toolText.wordWrap = True
        lay.addWidget(self.toolText)
        tools = qt.QHBoxLayout()
        self.toolButtons = {}
        for name in ['Draw', 'Paint', 'Erase']:
            b = self._button(name, lambda n=name: self.setTool(n), tools)
            b.setCheckable(True)
            self.toolButtons[name] = b
        lay.addLayout(tools)
        self.editor = slicer.qMRMLSegmentEditorWidget()
        self.editor.setMRMLScene(slicer.mrmlScene)
        self.editor.setMaximumNumberOfUndoStates(30)
        self.editor.setUndoEnabled(True)
        self.editor.setEffectNameOrder(['Draw', 'Paint', 'Erase'])
        self.editor.unorderedEffectsVisible = False
        self.editor.autoShowSourceVolumeNode = False
        for method in ['setSourceVolumeNodeSelectorVisible', 'setSegmentationNodeSelectorVisible', 'setSwitchToSegmentationsButtonVisible', 'setShow3DButtonVisible', 'setEffectButtonStyle']:
            if hasattr(self.editor, method) and method != 'setEffectButtonStyle':
                getattr(self.editor, method)(False)
        # Native editor owns the effects and undo history. Focused controls are exposed above.
        self.editor.hide()
        lay.addWidget(self.editor)
        brushRow = qt.QHBoxLayout()
        brushRow.addWidget(qt.QLabel('Brush diameter'))
        self.brushSize = qt.QDoubleSpinBox()
        self.brushSize.setRange(0.3, 30)
        self.brushSize.setSingleStep(0.5)
        self.brushSize.setSuffix(' mm')
        self.brushSize.setValue(float(self.settings.value('Meniscus/brush', 3)))
        self.brushSize.connect('valueChanged(double)', self._brush)
        brushRow.addWidget(self.brushSize)
        lay.addLayout(brushRow)
        row = qt.QHBoxLayout()
        self._button('Undo', self._undo, row)
        self._button('Redo', self._redo, row)
        lay.addLayout(row)
        displayPanel = ctk.ctkCollapsibleButton()
        displayPanel.text = 'Display and orientation'
        displayPanel.collapsed = True
        displayLayout = qt.QVBoxLayout(displayPanel)
        displayLayout.setSpacing(8)
        lay.addWidget(displayPanel)
        displayRow = qt.QHBoxLayout()
        self.visible = qt.QCheckBox('Show labels')
        self.visible.setChecked(True)
        self.visible.connect('toggled(bool)', self._display)
        displayRow.addWidget(self.visible)
        self.fill = qt.QCheckBox('Fill')
        self.fill.setChecked(True)
        self.fill.connect('toggled(bool)', self._display)
        displayRow.addWidget(self.fill)
        displayLayout.addLayout(displayRow)
        self.opacity = qt.QSlider(qt.Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(25)
        self.opacity.setToolTip('Transparent fill opacity; outline remains visible')
        self.opacity.connect('valueChanged(int)', self._display)
        displayLayout.addWidget(self.opacity)
        self._button('Reset view', self._resetView, displayLayout)
        self.reformats = qt.QCheckBox('Show orientation reformats')
        self.reformats.setToolTip('Secondary resliced views for orientation. Editing remains on the acquired Red view only.')
        self.reformats.connect('toggled(bool)', self._layoutViews)
        displayLayout.addWidget(self.reformats)
        self._title('Review and notes', lay)
        self.attention = qt.QCheckBox('This slice needs attention')
        self.attention.connect('toggled(bool)', self._flag)
        lay.addWidget(self.attention)
        self.notes = qt.QTextEdit()
        self.notes.setPlaceholderText('Case notes / uncertainty explanation')
        self.notes.setMaximumHeight(90)
        self.notes.connect('textChanged()', self._notesChanged)
        lay.addWidget(self.notes)
        self.medialConsidered = qt.QCheckBox('Medial compartment considered')
        self.lateralConsidered = qt.QCheckBox('Lateral compartment considered')
        for b in [self.medialConsidered, self.lateralConsidered]:
            b.connect('toggled(bool)', self._compartments)
            lay.addWidget(b)
        self.protocolLabel = qt.QLabel('Protocol: draft · practice work only')
        self.protocolLabel.objectName = 'support'
        self.protocolLabel.wordWrap = True
        lay.addWidget(self.protocolLabel)
        lay.addStretch(1)
        scroll = qt.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(qt.QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setStyleSheet(self.style)
        self.rightDock.setWidget(scroll)
        slicer.util.mainWindow().addDockWidget(qt.Qt.RightDockWidgetArea, self.rightDock)

    def _buildBars(self):
        main = slicer.util.mainWindow()
        self.topBar = qt.QToolBar('Case and view', main)
        self.topBar.objectName = 'MeniscusIdentity'
        self.topBar.setFont(self.font)
        self.topBar.setStyleSheet(self.style)
        self.topBar.setMovable(False)
        self.identityLabel = qt.QLabel('Meniscus annotation')
        self.identityLabel.objectName = 'identity'
        self.topBar.addWidget(self.identityLabel)
        cases = qt.QPushButton('Cases')
        cases.setCheckable(True)
        cases.setChecked(True)
        cases.connect('toggled(bool)', lambda visible: slicer.util.setModulePanelVisible(visible))
        self.topBar.addWidget(cases)
        tools = qt.QPushButton('Tools')
        tools.setCheckable(True)
        tools.setChecked(True)
        tools.connect('toggled(bool)', self.rightDock.setVisible)
        self.rightDock.connect('visibilityChanged(bool)', tools.setChecked)
        self.topBar.addWidget(tools)
        spacer = qt.QWidget()
        spacer.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)
        self.topBar.addWidget(spacer)
        self.saveStatus = qt.QLabel('Open a dataset to begin')
        self.topBar.addWidget(self.saveStatus)
        main.addToolBar(qt.Qt.TopToolBarArea, self.topBar)
        self.bottomBar = qt.QToolBar('Slice review', main)
        self.bottomBar.objectName = 'MeniscusReview'
        self.bottomBar.setMovable(False)
        self.bottomBar.setStyleSheet(self.style)
        self.bottomBar.setFont(self.font)
        self.sliceSpin = qt.QSpinBox()
        self.sliceSpin.setRange(1, 1)
        self.sliceSpin.setPrefix('Slice ')
        self.sliceSpin.connect('valueChanged(int)', lambda v: self.goSlice(v-1))
        self.bottomBar.addWidget(self.sliceSpin)
        for text, callback in [('Previous', lambda: self.goSlice(self.currentSlice-1)), ('Next', lambda: self.goSlice(self.currentSlice+1)), ('Reviewed → next slice', self._reviewNext), ('Next unreviewed', self._nextUnreviewed), ('Next flagged', self._nextFlagged)]:
            b = qt.QPushButton(text)
            b.connect('clicked()', callback)
            self.bottomBar.addWidget(b)
        self.progress = qt.QLabel('0 / 0 reviewed')
        self.bottomBar.addWidget(self.progress)
        main.addToolBar(qt.Qt.BottomToolBarArea, self.bottomBar)
        self.actionBar = qt.QToolBar('Save and approval', main)
        self.actionBar.objectName = 'MeniscusActions'
        self.actionBar.setMovable(False)
        self.actionBar.setFont(self.font)
        self.actionBar.setStyleSheet(self.style)
        for text, cb in [('Save draft', lambda: self._safe(self.save)), ('Approve case', self._approve), ('Next case', self._nextCase)]:
            b = qt.QPushButton(text)
            b.connect('clicked()', cb)
            self.actionBar.addWidget(b)
        self.message = qt.QLabel('Research annotation · source data is read-only')
        self.actionBar.addWidget(self.message)
        main.addToolBarBreak(qt.Qt.BottomToolBarArea)
        main.addToolBar(qt.Qt.BottomToolBarArea, self.actionBar)

    def _finishLayout(self):
        # Retain native Slicer MRI widgets, but remove unrelated toolbars from this focused workflow.
        for bar in slicer.util.mainWindow().findChildren(qt.QToolBar):
            if bar not in [self.topBar, self.bottomBar, self.actionBar]:
                bar.hide()
        slicer.util.setApplicationLogoVisible(False)
        slicer.util.setModuleHelpSectionVisible(False)
        slicer.util.setModulePanelTitleVisible(False)
        slicer.util.setDataProbeVisible(False)
        slicer.util.setPythonConsoleVisible(False)
        slicer.util.mainWindow().setWindowTitle('Meniscus Annotator ' + VERSION + ' · Research annotation')
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        # Remove general Slicer menu shortcuts (for example Save Scene) so only
        # focused view shortcuts act on annotations and notes keep normal text editing.
        for action in slicer.util.mainWindow().findChildren(qt.QAction):
            action.setShortcut(qt.QKeySequence())
        self._installShortcuts()
        slicer.util.mainWindow().resizeDocks([self.rightDock], [int(self.settings.value('Meniscus/toolsWidth', 310))], qt.Qt.Horizontal)
        self.rightDock.setMinimumWidth(260)
        self.parent.setMinimumWidth(260)
        caseDock = slicer.util.mainWindow().findChild(qt.QDockWidget, 'PanelDockWidget')
        if caseDock:
            caseDock.setStyleSheet('QDockWidget { background:#f3f5f7; }')
            slicer.util.mainWindow().resizeDocks([caseDock], [int(self.settings.value('Meniscus/casesWidth', 300))], qt.Qt.Horizontal)
        slicer.util.mainWindow().setMinimumSize(1024, 700)
        # Native view controller can reorient/reslice; focused workflow controls navigation instead.
        self._lockControllers()

    def _lockControllers(self):
        lm = slicer.app.layoutManager()
        for name in lm.sliceViewNames():
            w = lm.sliceWidget(name)
            w.sliceController().setVisible(False)
        if self.anatomy:
            # Restrict editing to the acquired-plane view even when reformats are shown.
            for node in [self.anatomy]:
                node.GetDisplayNode().RemoveAllViewNodeIDs()
                node.GetDisplayNode().AddViewNodeID(lm.sliceWidget('Red').mrmlSliceNode().GetID())

    def _installShortcuts(self):
        self.shortcuts = []
        view = slicer.app.layoutManager().sliceWidget('Red').sliceView()
        for key, cb in [('Left', lambda: self.goSlice(self.currentSlice-1)), ('Right', lambda: self.goSlice(self.currentSlice+1)), ('R', self._reviewNext), ('U', self._nextUnreviewed), ('F', self._nextFlagged), ('Ctrl+S', lambda: self._safe(self.save)), ('Ctrl+Z', self._undo), ('Ctrl+Y', self._redo), ('1', lambda: self.setLabel('medial')), ('2', lambda: self.setLabel('lateral')), ('3', lambda: self.setLabel('uncertain')), ('P', lambda: self.setTool('Paint')), ('D', lambda: self.setTool('Draw')), ('E', lambda: self.setTool('Erase')), ('Escape', lambda: self.setTool(''))]:
            shortcut = qt.QShortcut(qt.QKeySequence(key), view)
            shortcut.setContext(qt.Qt.WidgetWithChildrenShortcut)
            shortcut.connect('activated()', cb)
            self.shortcuts.append(shortcut)

    def _enable(self, enabled):
        self.rightDock.widget().setEnabled(enabled)
        self.bottomBar.setEnabled(enabled)
        self.actionBar.setEnabled(enabled)

    def _safe(self, func):
        try:
            return func()
        except Exception as exc:
            self._diagnostic = traceback.format_exc()
            reason = str(exc) if isinstance(exc, (ValidationError, OSError)) else 'The operation could not be completed.'
            self.message.setText('Action failed — saved checkpoints retained')
            slicer.util.errorDisplay(reason + '\n\nCheck the dataset or work location, available disk space and permissions, then retry. Diagnostic details are available in Help.', windowTitle='Meniscus annotation')
            return None

    def _chooseDataset(self):
        root = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Open dataset', str(self.settings.value('Meniscus/dataset', '')))
        if root:
            self._safe(lambda: self.openDataset(root))

    def openDataset(self, root, work_root=None):
        self.message.setText('Validating dataset…')
        slicer.app.processEvents()
        def progress(done, total):
            self.message.setText(f'Validating dataset: {done} of {total} scans…')
            slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            ds = Dataset(root, progress=progress)
        finally:
            qt.QApplication.restoreOverrideCursor()
        documents = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        version = ds.cases[0].metadata['dataset_version']
        remembered = self.settings.value('Meniscus/work/' + version, '')
        location = work_root or remembered or str(Path(documents) / 'Meniscus_annotation_work' / version)
        if not work_root and not remembered:
            dialog = qt.QMessageBox(slicer.util.mainWindow())
            dialog.setWindowTitle('Local work folder')
            dialog.setText('Annotations will be saved separately from the dataset.')
            dialog.setInformativeText(str(location))
            use = dialog.addButton('Use this folder', qt.QMessageBox.AcceptRole)
            change = dialog.addButton('Change location', qt.QMessageBox.ActionRole)
            dialog.exec_()
            if dialog.clickedButton() == change:
                chosen = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Choose local work folder', documents)
                if not chosen:
                    return
                location = str(Path(chosen) / version)
        job_path = str(self.settings.value('Meniscus/job/' + ds.identity, ''))
        job = json.loads(Path(job_path).read_text(encoding='utf-8')) if job_path else None
        store = WorkStore(location, ds, job=job)
        self.closeCase()
        self.dataset, self.store = ds, store
        self.settings.setValue('Meniscus/dataset', str(Path(root).resolve()))
        self.settings.setValue('Meniscus/work/' + version, str(location))
        self.datasetLabel.setText(version + '\n' + str(len(ds.cases)) + ' complete scans · local work folder connected')
        self._populate()
        self.message.setText('Dataset validated. Double-click a case to open.')
        return ds

    def _loadJob(self):
        if not self.dataset:
            slicer.util.warningDisplay('Open the dataset first.')
            return
        path = qt.QFileDialog.getOpenFileName(slicer.util.mainWindow(), 'Load explicit annotation job', '', 'JSON configuration (*.json)')
        if not path:
            return
        def load():
            job = json.loads(Path(path).read_text(encoding='utf-8'))
            self.closeCase()
            self.store = WorkStore(self.store.root, self.dataset, job=job)
            self.settings.setValue('Meniscus/job/' + self.dataset.identity, str(path))
            self.message.setText('Explicit job loaded. Open a case; only permitted starting masks will be loaded.')
        self._safe(load)

    def _populate(self):
        if not self.dataset:
            return
        self.caseTable.setRowCount(len(self.dataset.cases))
        for row, case in enumerate(self.dataset.cases):
            m = case.metadata
            identity = f"{m['participant_id']} · M{int(m['visit_month']):03d} · {'Left' if m['knee_side']=='L' else 'Right'}"
            item = qt.QTableWidgetItem(identity)
            item.setData(qt.Qt.UserRole, case.key)
            self.caseTable.setItem(row, 0, item)
            status = 'Not started'
            if self.session and self.session.case.key == case.key:
                status = 'Approved' if self.session.state.get('status') in ('approved', 'practice_approved') else ('Needs review' if any(not r['reviewed'] for r in self.session.state['review']) else 'In progress')
            elif hasattr(self.store, 'summary'):
                summary = self.store.summary(case)
                status = {'approved':'Approved', 'practice_approved':'Approved', 'not_started':'Not started', 'needs_review':'Needs review', 'in_progress':'In progress'}.get(summary.get('status'), 'In progress')
            self.caseTable.setItem(row, 1, qt.QTableWidgetItem(status))
        self._filter()

    def _filter(self, *args):
        query = str(self.search.text).casefold()
        selected = str(self.progressFilter.currentText)
        for row in range(self.caseTable.rowCount):
            text = str(self.caseTable.item(row, 0).text()).casefold()
            status = str(self.caseTable.item(row, 1).text())
            self.caseTable.setRowHidden(row, query not in text or (selected != 'All cases' and selected != status))

    def _openRow(self, row, col=0):
        if row >= 0:
            key = self.caseTable.item(row, 0).data(qt.Qt.UserRole)
            self._safe(lambda: self.openCase(key))

    def _resume(self):
        if not self.dataset:
            root = str(self.settings.value('Meniscus/dataset', ''))
            if not root or self._safe(lambda: self.openDataset(root)) is None:
                return
        key = str(self.settings.value('Meniscus/lastCase', ''))
        if key:
            self._safe(lambda: self.openCase(key))

    def closeCase(self):
        if not self.session:
            return
        if not self._loading:
            self._segmentChanged()  # Commit a queued native stroke before switching/closing.
        if self.dirty:
            self.save()
        self._loading = True
        for node, tag in self._observers:
            node.RemoveObserver(tag)
        self._observers.clear()
        self.editor.setSegmentationNode(None)
        self.editor.setSourceVolumeNode(None)
        self.session.close()
        self.session = None
        for node in [self.volume, self.anatomy, getattr(self, 'editorNode', None)]:
            if node:
                display = node.GetDisplayNode() if hasattr(node, 'GetDisplayNode') else None
                storage = node.GetStorageNode() if hasattr(node, 'GetStorageNode') else None
                slicer.mrmlScene.RemoveNode(node)
                for helper in [display, storage]:
                    if helper:
                        slicer.mrmlScene.RemoveNode(helper)
        self.volume = self.anatomy = self.uncertainty = None
        self._loading = False
        self._enable(False)

    def openCase(self, key):
        if self.session and self.session.case.key == key:
            return
        self.closeCase()
        case = next(c for c in self.dataset.cases if c.key == key)
        self.session = self.store.open_case(case)
        self._loading = True
        try:
            labels, uncertain, seg_path = self.session.load()
            self.volume = slicer.util.loadVolume(str(case.image_path), {'name':'Source MRI', 'singleFile':True})
            if not self.volume:
                raise ValidationError('The source MRI could not be loaded.')
            self.volume.SetSaveWithScene(False)
            self.volume.GetDisplayNode().SetSaveWithScene(False)
            self.volume.GetStorageNode().SetSaveWithScene(False)
            import hashlib
            self._volumeDigest = hashlib.sha256(slicer.util.arrayFromVolume(self.volume).tobytes()).hexdigest()
            matrix = vtk.vtkMatrix4x4()
            self.volume.GetIJKToRASMatrix(matrix)
            actual = np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
            if tuple(self.volume.GetImageData().GetDimensions()) != tuple(case.shape_xyz) or not np.allclose(actual, case.affine_ras, atol=1e-4, rtol=0):
                raise ValidationError('Slicer loaded a different image grid. Editing is blocked.')
            self.anatomy = self._newSegmentation('Meniscus annotation', ['medial', 'lateral', 'uncertain'])
            self.uncertainty = self.anatomy  # Separate binary segment, allowed to overlap anatomy.
            for segid, value in [('medial',1), ('lateral',2)]:
                slicer.util.updateSegmentBinaryLabelmapFromArray((labels==value).astype(np.uint8), self.anatomy, segid, self.volume)
            slicer.util.updateSegmentBinaryLabelmapFromArray(uncertain.astype(np.uint8), self.uncertainty, 'uncertain', self.volume)
            self.editorNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentEditorNode')
            self.editorNode.SetSaveWithScene(False)
            self.editor.setMRMLSegmentEditorNode(self.editorNode)
            self.editorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
            self.editor.setSegmentationNode(self.anatomy)
            self.editor.setSourceVolumeNode(self.volume)
            self.editor.setCurrentSegmentID('medial')
            self.editor.setActiveEffectByName('Paint')
            self._configureEffects()
            self._lastArrays = self.collectArrays()
            for node in [self.anatomy]:
                # Voxel changes do not always modify segment properties. Observe
                # source/derived representations as well as segment metadata.
                for event in [slicer.vtkSegmentation.SourceRepresentationModified,
                              slicer.vtkSegmentation.RepresentationModified,
                              slicer.vtkSegmentation.SegmentModified]:
                    tag = node.GetSegmentation().AddObserver(event, self._queueSegmentChanged)
                    self._observers.append((node.GetSegmentation(),tag))
            slicer.util.setSliceViewerLayers(background=self.volume)
            self._layoutViews()
            resume_key = 'Meniscus/slice/' + self.session.case.identity
            self.currentSlice = int(self.settings.value(resume_key, self.session.state.get('last_slice', 0)))
            self._nativePlane(self.currentSlice, reset=True)
            sliceNode = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode()
            self._observers.append((sliceNode, sliceNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self._sliceMoved)))
            self.sliceSpin.setMaximum(case.n_slices)
            self.sliceSpin.setSuffix(' / ' + str(case.n_slices))
            self.notes.setPlainText(self.session.state.get('notes', ''))
            self.medialConsidered.setChecked(self.session.state['compartments']['medial'])
            self.lateralConsidered.setChecked(self.session.state['compartments']['lateral'])
            self.protocolLabel.setText('Protocol: ' + self.session.state['protocol']['version'] + ' · ' + self.session.state['protocol']['status'])
            self.dirty = False
            self._enable(True)
            self.setLabel('medial')
            self.setTool('Paint')
            self.settings.setValue('Meniscus/lastCase', key)
        except Exception:
            self.dirty = False
            self._loading = True  # Release a partial load without trying to serialize missing nodes.
            self.closeCase()
            raise
        self._loading = False
        self.refreshReview()
        self._populate()
        if self.session.recovered:
            self.message.setText('Recovered the most recent intact checkpoint. A newer checkpoint was damaged; preserve the work folder for diagnostics.')
        return self.session

    def _newSegmentation(self, name, ids):
        node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', name)
        node.SetSaveWithScene(False)
        node.CreateDefaultDisplayNodes()
        node.GetDisplayNode().SetSaveWithScene(False)
        node.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
        for key in ids:
            name, color = LABELS[key]
            node.GetSegmentation().AddEmptySegment(key, name, color)
        return node

    def _configureEffects(self):
        for name in ['Paint', 'Erase']:
            effect = self.editor.effectByName(name)
            for param, value in [('BrushSphere',0), ('BrushPixelMode',0), ('BrushDiameterIsRelative',0), ('EditIn3DViews',0), ('BrushAbsoluteDiameter',self.brushSize.value)]:
                effect.setParameter(param, value)

    def _nativePlane(self, k, reset=False):
        if not self.volume:
            return
        a = self.session.case.affine_ras
        normal = a[:3,2]/np.linalg.norm(a[:3,2])
        up = a[:3,1]/np.linalg.norm(a[:3,1])
        horizontal = np.cross(up, normal)
        centre = a @ np.array([(self.session.case.shape_xyz[0]-1)/2, (self.session.case.shape_xyz[1]-1)/2, k, 1])
        node = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode()
        mat = node.GetSliceToRAS()
        # Preserve in-plane pan when stepping, but always snap onto one acquired plane.
        position = centre[:3] if reset else np.array([mat.GetElement(i,3) for i in range(3)])
        position += normal * (np.dot(normal, centre[:3])-np.dot(normal, position))
        self._snap = True
        try:
            for i in range(3):
                mat.SetElement(i,0,float(horizontal[i]))
                mat.SetElement(i,1,float(up[i]))
                mat.SetElement(i,2,float(normal[i]))
                mat.SetElement(i,3,float(position[i]))
            node.UpdateMatrices()
            annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
            for edge, direction in [(vtk.vtkCornerAnnotation.LeftEdge, -horizontal), (vtk.vtkCornerAnnotation.RightEdge, horizontal), (vtk.vtkCornerAnnotation.UpperEdge, up), (vtk.vtkCornerAnnotation.LowerEdge, -up)]:
                annotation.SetText(edge, node.GetDirectionLabel(direction.tolist()))
            annotation.GetTextProperty().SetColor(0.88, 0.91, 0.94)
            annotation.GetTextProperty().SetFontFamilyToArial()
            annotation.GetTextProperty().SetBold(False)
            annotation.SetMaximumFontSize(16)
            node.SetSliceSpacingModeToPrescribed()
            spacing = np.linalg.norm(a[:3,:3],axis=0)
            node.SetPrescribedSliceSpacing(float(spacing[0]),float(spacing[1]),float(spacing[2]))
            if reset:
                slicer.app.layoutManager().sliceWidget('Red').sliceLogic().FitSliceToAll()
        finally:
            self._snap = False

    def _sliceMoved(self, *args):
        if self._snap or self._loading or not self.session:
            return
        node = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode()
        p = np.array([node.GetSliceToRAS().GetElement(i,3) for i in range(3)]+[1])
        k = int(np.clip(round((np.linalg.inv(self.session.case.affine_ras) @ p)[2]),0,self.session.case.n_slices-1))
        self.goSlice(k)

    def goSlice(self, k):
        if not self.session:
            return
        k = int(np.clip(k,0,self.session.case.n_slices-1))
        self.currentSlice = k
        self.session.state['last_slice'] = k
        self._nativePlane(k)
        self.refreshReview()
        if not self._loading:
            self.settings.setValue('Meniscus/slice/' + self.session.case.identity, k)
            self.settings.sync()  # Resume position does not alter an approved annotation.

    def _assertGrid(self):
        if self.volume.GetParentTransformNode():
            raise ValidationError('The source volume has a transform. Reopen the case on its original grid.')
        matrix = vtk.vtkMatrix4x4()
        self.volume.GetIJKToRASMatrix(matrix)
        actual = np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
        if tuple(self.volume.GetImageData().GetDimensions()) != tuple(self.session.case.shape_xyz) or not np.allclose(actual, self.session.case.affine_ras, atol=1e-4, rtol=0):
            self.editor.setActiveEffectByName('')
            raise ValidationError('The source volume grid changed. Reopen this case before editing or saving.')

    def collectArrays(self):
        self._assertGrid()
        medial = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'medial',self.volume).astype(bool)
        lateral = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'lateral',self.volume).astype(bool)
        if np.any(medial & lateral):
            raise ValidationError('Medial and lateral labels overlap. Resolve the overlap before saving.')
        uncertain = slicer.util.arrayFromSegmentBinaryLabelmap(self.uncertainty,'uncertain',self.volume).astype(np.uint8)
        return medial.astype(np.uint8) + 2*lateral.astype(np.uint8), uncertain

    def _queueSegmentChanged(self, *args):
        if self._loading or self._updating or self._editQueued:
            return
        self._editQueued = True
        qt.QTimer.singleShot(0, lambda: self._safe(self._segmentChanged))

    def _segmentChanged(self, *args):
        self._editQueued = False
        if self._loading or self._updating or not self.session:
            return
        self._updating = True
        try:
            # Native effects may permit overlapping segments. Resolve anatomy explicitly,
            # preserving the independent uncertainty segment and native undo transaction.
            medial = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy, 'medial', self.volume).astype(bool)
            lateral = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy, 'lateral', self.volume).astype(bool)
            overlap = medial & lateral
            if overlap.any():
                if self.activeLabel not in ('medial', 'lateral'):
                    raise ValidationError('Anatomical overlap detected. Reopen the latest verified checkpoint.')
                other = 'lateral' if self.activeLabel == 'medial' else 'medial'
                other_array = lateral if other == 'lateral' else medial
                slicer.util.updateSegmentBinaryLabelmapFromArray((other_array & ~overlap).astype(np.uint8), self.anatomy, other, self.volume)
            arrays = self.collectArrays()
            changed = np.flatnonzero(np.any((arrays[0] != self._lastArrays[0]) | (arrays[1] != self._lastArrays[1]), axis=(1,2)))
            if len(changed):
                self.session.mark_changed([int(k) for k in changed])
                self._lastArrays = tuple(a.copy() for a in arrays)
                self.dirty = True
                self.refreshReview()
        except Exception:
            self.editor.setActiveEffectByName('')
            raise
        finally:
            self._updating = False

    def setLabel(self, key):
        if not self.session:
            return
        self._segmentChanged()
        self.activeLabel = key
        previousTool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Paint'
        if self.editor.segmentationNode() != self.anatomy:
            self.editor.setSegmentationNode(self.anatomy)
        self.editor.setCurrentSegmentID(key)
        self.editor.setActiveEffectByName(previousTool)
        self._configureEffects()
        for k, b in self.labelButtons.items():
            b.setChecked(k == key)
        self.labelCombo.blockSignals(True)
        self.labelCombo.setCurrentIndex(list(LABELS).index(key))
        self.labelCombo.blockSignals(False)
        self._toolStatus()

    def setTool(self, name):
        if not self.session:
            return
        self._segmentChanged()
        self.editor.setActiveEffectByName(name)
        self._configureEffects()
        for n, b in self.toolButtons.items():
            b.setChecked(n == name)
        self._toolStatus()

    def _toolStatus(self):
        tool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Navigate'
        self.toolText.setText(f'{LABELS[self.activeLabel][0]} · {tool} · {self.brushSize.value:g} mm\nScope: current acquired slice')

    def _brush(self, *args):
        self.settings.setValue('Meniscus/brush', self.brushSize.value)
        if self.session:
            self._configureEffects()
            self._toolStatus()

    def _undo(self):
        if self.session:
            self.editor.undo()
            self._segmentChanged()

    def _redo(self):
        if self.session:
            self.editor.redo()
            self._segmentChanged()

    def _display(self, *args):
        if not self.anatomy:
            return
        for node in [self.anatomy]:
            d = node.GetDisplayNode()
            d.SetVisibility(self.visible.checked)
            d.SetOpacity2DFill(self.opacity.value/100 if self.fill.checked else 0)
            d.SetOpacity2DOutline(1)

    def _layoutViews(self, *args):
        lm = slicer.app.layoutManager()
        lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView if self.reformats.checked else slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        # Four-up includes an optional 3D orientation view, not an editing surface.
        self._lockControllers()
        if self.volume:
            self._nativePlane(self.currentSlice)
            self._display()

    def _resetView(self):
        if self.session:
            self._nativePlane(self.currentSlice, reset=True)
            self.volume.GetDisplayNode().AutoWindowLevelOn()

    def _changed(self):
        if self._loading or not self.session:
            return
        if self.session.state.get('status') in ('approved', 'practice_approved'):
            self.session.state.update(status='needs_review', approval=None, approver=None)
        self.dirty = True
        self.refreshReview()

    def _notesChanged(self):
        if self.session and not self._loading:
            self.session.state['notes'] = str(self.notes.toPlainText())
            self._changed()

    def _compartments(self, *args):
        if self.session and not self._loading:
            self.session.state['compartments'] = {'medial': self.medialConsidered.checked, 'lateral': self.lateralConsidered.checked}
            self._changed()

    def _flag(self, checked):
        if self.session and not self._loading:
            self.session.state['review'][self.currentSlice]['flag'] = bool(checked)
            self._changed()

    def _reviewNext(self):
        if self.session:
            self._segmentChanged()
            self.session.state['review'][self.currentSlice]['reviewed'] = True
            self._changed()
            self.goSlice(self.currentSlice+1)
            self._safe(self.save)

    def _jump(self, predicate):
        if self.session:
            n = self.session.case.n_slices
            for step in range(1,n+1):
                k = (self.currentSlice+step)%n
                if predicate(self.session.state['review'][k]):
                    self.goSlice(k)
                    return
            self.message.setText('No matching slices.')

    def _nextUnreviewed(self):
        self._jump(lambda r: not r['reviewed'])

    def _nextFlagged(self):
        self._jump(lambda r: r['flag'])

    def refreshReview(self):
        if not self.session:
            return
        m = self.session.case.metadata
        self.identityLabel.setText(f"OAI {m['participant_id']}   ·   M{int(m['visit_month']):03d}   ·   {'Left' if m['knee_side']=='L' else 'Right'} knee")
        review = self.session.state['review']
        count = sum(bool(r['reviewed']) for r in review)
        flags = sum(bool(r['flag']) for r in review)
        self.progress.setText(f'  {count} / {len(review)} reviewed · {flags} flagged  ')
        self.sliceSpin.blockSignals(True)
        self.sliceSpin.setValue(self.currentSlice+1)
        self.sliceSpin.blockSignals(False)
        self.attention.blockSignals(True)
        self.attention.setChecked(review[self.currentSlice]['flag'])
        self.attention.blockSignals(False)
        state = 'Reviewed' if review[self.currentSlice]['reviewed'] else 'Not reviewed'
        self.saveStatus.setText(('Unsaved changes' if self.dirty else 'Saved') + ' · ' + state + '  ')
        self.message.setText('Practice protocol · approval is Jeff’s own review' if self.session.state['protocol']['status']=='draft' else 'Annotation protocol ' + self.session.state['protocol']['version'])

    def _segWriter(self, path):
        # One editable segmentation contains all fixed IDs. Separate layers preserve uncertainty overlap.
        combined = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Checkpoint')
        combined.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
        try:
            for node, ids in [(self.anatomy,['medial','lateral']), (self.uncertainty,['uncertain'])]:
                for key in ids:
                    if not combined.GetSegmentation().CopySegmentFromSegmentation(node.GetSegmentation(),key):
                        raise ValidationError('Could not preserve the editable segmentation.')
            storage = combined.CreateDefaultStorageNode()
            slicer.mrmlScene.AddNode(storage)
            combined.SetAndObserveStorageNodeID(storage.GetID())
            storage.SetCropToMinimumExtent(False)
            if not slicer.util.saveNode(combined, str(path)):
                raise OSError('Could not write the editable segmentation. Check disk space and permissions.')
            # Reopen with Slicer's independent storage reader and compare against full reference arrays.
            reopened = slicer.util.loadSegmentation(str(path))
            try:
                for key,node in [('medial',self.anatomy),('lateral',self.anatomy),('uncertain',self.uncertainty)]:
                    if not np.array_equal(slicer.util.arrayFromSegmentBinaryLabelmap(reopened,key,self.volume), slicer.util.arrayFromSegmentBinaryLabelmap(node,key,self.volume)):
                        raise ValidationError('Reopened editable segmentation differs from the annotation.')
            finally:
                if reopened:
                    helpers = [reopened.GetDisplayNode(), reopened.GetStorageNode()]
                    slicer.mrmlScene.RemoveNode(reopened)
                    for helper in helpers:
                        if helper:
                            slicer.mrmlScene.RemoveNode(helper)
        finally:
            helpers = [combined.GetDisplayNode(), combined.GetStorageNode()]
            slicer.mrmlScene.RemoveNode(combined)
            for helper in helpers:
                if helper:
                    slicer.mrmlScene.RemoveNode(helper)

    def save(self, approve=False, practice=False):
        if not self.session:
            return
        self._segmentChanged()
        self._assertGrid()
        import hashlib
        if hashlib.sha256(slicer.util.arrayFromVolume(self.volume).tobytes()).hexdigest() != self._volumeDigest:
            self.editor.setActiveEffectByName('')
            raise ValidationError('The loaded source image pixels changed. Reopen the case before saving.')
        self.saveStatus.setText('Saving…')
        labels, uncertain = self.collectArrays()
        self.session.state['runtime'] = {'slicer_version':slicer.app.applicationVersion, 'slicer_revision':slicer.app.repositoryRevision, 'application_version':VERSION}
        path = self.session.save(labels, uncertain, self._segWriter, approve=approve, practice=practice)
        self.dirty = False
        self.refreshReview()
        self._populate()
        self.saveStatus.setText(('Approved practice' if practice else 'Approved') + ' · Saved' if approve else 'Saved · checkpoint verified')
        return path

    def _approve(self):
        if not self.session:
            return
        practice = self.session.state['protocol']['status'] == 'draft'
        labels, uncertain = self.collectArrays()
        errors = self.session.approval_errors(labels, uncertain, practice=practice)
        if errors:
            slicer.util.warningDisplay('Approval is unavailable:\n\n' + '\n'.join('• ' + e for e in errors),windowTitle='Review required')
            return
        text = ('This protocol is a draft. This creates an approved PRACTICE version, excluded from research exports.\n\n' if practice else '') + 'I, Jeff, have considered both compartments and reviewed every acquired slice under the recorded protocol. This is my own approval, not an independent second-reader assessment.\n\nApprove this version?'
        if slicer.util.confirmYesNoDisplay(text,windowTitle='Approve case'):
            self._safe(lambda: self.save(approve=True,practice=practice))

    def _nextCase(self):
        if self.dataset:
            index = next((i for i,c in enumerate(self.dataset.cases) if self.session and c.key==self.session.case.key), -1)
            self._safe(lambda: self.openCase(self.dataset.cases[(index+1)%len(self.dataset.cases)].key))

    def _autosave(self):
        if self.session and self.dirty:
            try:
                self.save()
            except Exception:
                self._diagnostic = traceback.format_exc()
                self.saveStatus.setText('Autosave failed · Unsaved changes')
                self.message.setText('Check disk space and work-folder permissions, then use Save draft. Previous checkpoints are intact.')

    def _showWork(self):
        if self.store:
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(self.store.root)))

    def _exportDialog(self):
        if not self.store:
            return
        chosen_rows = sorted({index.row() for index in self.caseTable.selectedIndexes()})
        chosen_keys = [self.caseTable.item(row,0).data(qt.Qt.UserRole) for row in chosen_rows]
        dialog = qt.QDialog(slicer.util.mainWindow())
        dialog.setWindowTitle('Export results')
        layout = qt.QVBoxLayout(dialog)
        layout.addWidget(qt.QLabel('Export verified approved checkpoints without MRI images.'))
        selected = qt.QCheckBox('Selected cases only (' + str(len(chosen_keys)) + ')')
        selected.setEnabled(bool(chosen_keys))
        layout.addWidget(selected)
        practice = qt.QCheckBox('Practice results (separate from research approval)')
        layout.addWidget(practice)
        buttons = qt.QDialogButtonBox(qt.QDialogButtonBox.Ok | qt.QDialogButtonBox.Cancel)
        buttons.connect('accepted()',dialog.accept)
        buttons.connect('rejected()',dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != qt.QDialog.Accepted:
            return
        if self.session and self.dirty and self._safe(self.save) is None:
            return
        documents = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        target = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Export results to folder', documents)
        if not target:
            return
        keys = None
        if selected.checked:
            keys = chosen_keys
        result = self._safe(lambda: export_approved(self.store, Path(target)/'Meniscus_annotation_results', case_keys=keys, include_practice=practice.checked))
        if result:
            self._lastExport = result
            self.message.setText('Export verified: ' + Path(result).name)
            notice = qt.QMessageBox(slicer.util.mainWindow())
            notice.setWindowTitle('Export complete')
            notice.setText('Results ZIP created and checked.\n\n' + Path(result).name)
            showFile = notice.addButton('Show exported file', qt.QMessageBox.ActionRole)
            notice.addButton(qt.QMessageBox.Close)
            notice.exec_()
            if notice.clickedButton() == showFile:
                qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(Path(result).parent)))

    def _help(self):
        text = 'Meniscus Annotator ' + VERSION + '\n\nOpen dataset → Open case → Draw → Review every slice → Save draft → Approve → Export.\n\nMRI view shortcuts (inactive while typing notes):\nLeft / Right: acquired slice · R: reviewed and next\nU: next unreviewed · F: next flagged\n1 / 2 / 3: medial / lateral / uncertain\nP / D / E: paint / draw / erase · Esc: navigate\nCtrl+S: save · Ctrl+Z / Ctrl+Y: undo / redo\n\nNative Slicer mouse controls:\nCtrl+wheel: zoom · middle drag: pan\nRight drag: window/level · wheel: slice\nDraw: left-click contour points, right-click to apply.\n\nEvery changed slice requires review again. Uncertainty is a separate overlapping mask and blocks approval until resolved. Draft protocols allow practice approval only. Saved versions recover work after restart; in-memory undo history does not survive restart.\n\nHelp → Diagnostics includes details of the last error.'
        dialog = qt.QMessageBox(slicer.util.mainWindow())
        dialog.setWindowTitle('Setup and shortcut help')
        dialog.setText(text)
        diagnostics = dialog.addButton('Diagnostics', qt.QMessageBox.ActionRole)
        restore = dialog.addButton('Restore last saved case', qt.QMessageBox.ActionRole)
        dialog.addButton(qt.QMessageBox.Close)
        dialog.exec_()
        if dialog.clickedButton() == restore and self.session:
            if slicer.util.confirmYesNoDisplay('Discard unsaved changes and reopen the last verified checkpoint? Previous saved versions will remain intact.', windowTitle='Restore saved case'):
                key = self.session.case.key
                self.dirty = False
                self._loading = True
                self.closeCase()
                self._safe(lambda: self.openCase(key))
        if dialog.clickedButton() == diagnostics:
            slicer.util.infoDisplay(self._diagnostic or 'No errors recorded in this session.',windowTitle='Local diagnostic details — keep private')

    def _quit(self):
        if self.session:
            try:
                self.closeCase()
            except Exception:
                # Periodic verified checkpoints remain recoverable; never pretend exit saved.
                self._diagnostic = traceback.format_exc()
        caseDock = slicer.util.mainWindow().findChild(qt.QDockWidget, 'PanelDockWidget')
        if caseDock:
            self.settings.setValue('Meniscus/casesWidth', caseDock.width)
        self.settings.setValue('Meniscus/toolsWidth', self.rightDock.width)
        self.settings.sync()

    def cleanup(self):
        self.dirty = False  # aboutToQuit/close guard saves while native modules are still alive.
        if hasattr(self, 'autosave'):
            self.autosave.stop()
        self.closeCase()
        for name in ['rightDock', 'topBar', 'bottomBar', 'actionBar']:
            widget = getattr(self, name, None)
            if widget:
                widget.hide()
                widget.deleteLater()
