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
from MeniscusAnnotatorLib.core import load_job_config, load_dataset_job_config, correction_inputs_present
from MeniscusAnnotatorLib.build_identity import capture_source_identity

VERSION = '0.1.0'
SOURCE_IDENTITY = capture_source_identity()
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
        parent.title = 'Meniscus Annotator'
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
        self._windowLevelActive = False
        self._lastExport = None
        self._diagnostic = ''
        config_path = os.environ.get('MENISCUS_SOFTWARE_PRACTICE_CONFIG') or os.environ.get('MENISCUS_REAL_PRACTICE_CONFIG')
        self._practiceConfig = json.loads(Path(config_path).read_text(encoding='utf-8')) if config_path else None
        settings_file = os.environ.get('MENISCUS_SETTINGS_FILE')
        self.settings = qt.QSettings(settings_file,qt.QSettings.IniFormat) if settings_file else qt.QSettings()
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
        from MeniscusAnnotatorLib.interface import icon, checkmark_path
        self._icon = icon
        families = list(qt.QFontDatabase().families())
        if sys.platform == 'win32':
            family = 'Segoe UI Variable' if 'Segoe UI Variable' in families else 'Segoe UI'
        else:
            family = qt.QFontDatabase.systemFont(qt.QFontDatabase.GeneralFont).family()
        self.font = qt.QFont(family, 11)
        self.parent.setFont(self.font)
        self.style = '''
        QWidget { color:#263642; font-size:11pt; font-weight:400; }
        QWidget#workspacePanel { background:#f3f5f7; }
        QWidget#navigationPanel, QToolBar { background:#f8f9fb; border:0; }
        QToolBar { spacing:8px; padding:6px 12px; border-bottom:1px solid #d9e0e6; }
        QDockWidget { background:#f3f5f7; border:0; }
        QLabel { background:transparent; }
        QLabel#appTitle { font-size:13pt; font-weight:600; color:#233743; }
        QLabel#identity { font-size:11pt; color:#405461; }
        QLabel#panelTitle { font-size:11pt; font-weight:600; margin-top:3px; }
        QLabel#support { color:#60717e; }
        QLabel#sliceReadout { font-size:14pt; font-weight:600; color:#233743; }
        QLabel#saveState { font-weight:600; padding:0 8px; }
        QPushButton, QToolButton { background:#ffffff; border:1px solid #c4ced7; border-radius:4px; min-height:28px; padding:3px 9px; }
        QPushButton:hover, QToolButton:hover { background:#edf3f7; border-color:#8fa4b4; }
        QPushButton:checked, QToolButton:checked { background:#e4f0f8; border:1px solid #2874a0; color:#174f70; }
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:2px solid #2874a0; }
        QPushButton:disabled, QToolButton:disabled { color:#88949d; background:#eef1f4; border-color:#dbe1e6; }
        QPushButton#primary { background:#246d98; color:white; border-color:#246d98; font-weight:600; }
        QPushButton#primary:hover { background:#195a80; }
        QPushButton#primary:disabled { color:#88949d; background:#eef1f4; border-color:#dbe1e6; }
        QPushButton#quiet, QToolButton#quiet { border-color:transparent; background:transparent; }
        QPushButton#quiet:hover, QToolButton#quiet:hover { background:#e5ebf0; }
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#ffffff; border:1px solid #c4ced7; border-radius:3px; padding:5px; min-height:22px; selection-background-color:#c9e0f0; selection-color:#203340; }
        QTableWidget { background:#ffffff; color:#263642; border:0; gridline-color:#e5eaef; selection-background-color:#dfedf7; selection-color:#203340; }
        QHeaderView::section { background:#f3f5f7; color:#60717e; border:0; border-bottom:1px solid #d9e0e6; padding:6px; font-size:10pt; }
        QCheckBox { background:transparent; spacing:7px; min-height:26px; }
        QCheckBox::indicator { width:18px; height:18px; background:white; border:1px solid #8a9ba8; border-radius:3px; }
        QCheckBox::indicator:checked { background:#246d98; border-color:#246d98; image:url(CHECKMARK); }
        QCheckBox::indicator:disabled { border-color:#cbd3d9; background:#e8edf0; }
        QSlider::groove:horizontal { height:5px; background:#cfd9e1; border-radius:2px; }
        QSlider::sub-page:horizontal { background:#82afca; border-radius:2px; }
        QSlider::handle:horizontal { background:#246d98; border:2px solid #ffffff; width:16px; height:16px; margin:-7px 0; border-radius:8px; }
        QSlider::handle:horizontal:focus { border:2px solid #163f59; }
        QSlider::groove:horizontal:disabled { background:#dfe5e9; }
        QSlider::handle:horizontal:disabled { background:#aebcc6; }
        ctkCollapsibleButton { background:#f3f5f7; color:#405461; border:0; border-top:1px solid #dce3e9; padding:7px 0; text-align:left; }
        QMenu { background:#ffffff; color:#263642; border:1px solid #c4ced7; padding:5px; }
        QMenu::item { padding:7px 20px 7px 9px; }
        QMenu::item:selected { background:#dfedf7; }
        '''.replace('CHECKMARK', checkmark_path())
        self.parent.setStyleSheet(self.style)

    def _title(self, text, layout):
        label = qt.QLabel(text)
        label.objectName = 'panelTitle'
        layout.addWidget(label)
        return label

    def _button(self, text, callback, layout, primary=False, icon=None):
        button = qt.QPushButton(text)
        if primary:
            button.objectName = 'primary'
        if icon:
            button.setIcon(self._icon(icon, '#ffffff' if primary else '#425363'))
            button.setIconSize(qt.QSize(18,18))
        button.connect('clicked()', callback)
        layout.addWidget(button)
        return button

    def _panel(self):
        panel = qt.QWidget()
        panel.objectName = 'workspacePanel'
        panel.setFont(self.font)
        panel.setAttribute(qt.Qt.WA_StyledBackground, True)
        panel.setStyleSheet(self.style)
        layout = qt.QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        return panel, layout

    def _buildCases(self):
        self.caseListDock = qt.QDockWidget('Cases', slicer.util.mainWindow())
        self.caseListDock.objectName = 'MeniscusCasesDock'
        self.caseListDock.setFeatures(qt.QDockWidget.NoDockWidgetFeatures)
        self.caseListDock.setTitleBarWidget(qt.QWidget(self.caseListDock))
        panel, lay = self._panel()
        self._title('Cases', lay)
        self.search = qt.QLineEdit()
        self.search.placeholderText = 'Search OAI ID'
        self.search.setClearButtonEnabled(True)
        self.search.connect('textChanged(QString)', self._filter)
        lay.addWidget(self.search)
        self.progressFilter = qt.QComboBox()
        self.progressFilter.addItems(['All cases', 'Not started', 'In progress', 'Needs review', 'Approved', 'Blocked', 'Saved work needs attention'])
        self.progressFilter.connect('currentIndexChanged(int)', self._filter)
        lay.addWidget(self.progressFilter)
        self.caseTable = qt.QTableWidget(0,2)
        palette = self.caseTable.palette
        for role in [qt.QPalette.Text,qt.QPalette.WindowText,qt.QPalette.ButtonText]:
            palette.setColor(role,qt.QColor('#263642'))
        palette.setColor(qt.QPalette.Base,qt.QColor('white'))
        palette.setColor(qt.QPalette.Highlight,qt.QColor('#dfedf7'))
        palette.setColor(qt.QPalette.HighlightedText,qt.QColor('#203340'))
        self.caseTable.palette = palette
        self.caseTable.horizontalHeader().palette = palette
        self.caseTable.setHorizontalHeaderLabels(['Participant / visit', 'Progress'])
        self.caseTable.verticalHeader().hide()
        self.caseTable.verticalHeader().setDefaultSectionSize(56)
        self.caseTable.horizontalHeader().setStretchLastSection(True)
        self.caseTable.horizontalHeader().minimumSectionSize = 60
        self.caseTable.setColumnWidth(0,130)
        self.caseTable.setShowGrid(False)
        self.caseTable.setAlternatingRowColors(False)
        self.caseTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.caseTable.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.caseTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.caseTable.connect('cellDoubleClicked(int,int)',self._openRow)
        lay.addWidget(self.caseTable,1)
        self.openCaseButton = self._button('Open selected case',lambda:self._openRow(self.caseTable.currentRow(),0),lay,icon='next')
        row = qt.QHBoxLayout()
        self.resumeButton = self._button('Resume work',self._resume,row,icon='resume')
        self._button('Next case',self._nextCase,row,icon='next')
        lay.addLayout(row)
        self.datasetLabel = qt.QLabel('No dataset open')
        self.datasetLabel.objectName = 'support'
        self.datasetLabel.wordWrap = True
        lay.addWidget(self.datasetLabel)
        self.message = qt.QLabel('Open a dataset to begin.')
        self.message.objectName = 'support'
        self.message.wordWrap = True
        self.message.setMaximumHeight(72)
        lay.addWidget(self.message)
        self.caseListDock.setWidget(panel)
        self.caseListDock.setMinimumWidth(250)
        slicer.util.mainWindow().addDockWidget(qt.Qt.LeftDockWidgetArea,self.caseListDock)

    def _buildEditor(self):
        self.rightDock = qt.QDockWidget('Annotation',slicer.util.mainWindow())
        self.rightDock.objectName = 'MeniscusAnnotationTools'
        self.rightDock.setFeatures(qt.QDockWidget.NoDockWidgetFeatures)
        self.rightDock.setTitleBarWidget(qt.QWidget(self.rightDock))
        panel, lay = self._panel()
        self._title('Annotation',lay)
        labels = qt.QHBoxLayout()
        self.labelButtons = {}
        for key in ['medial','lateral']:
            name,color = LABELS[key]
            b = self._button('Medial' if key=='medial' else 'Lateral',lambda k=key:self.setLabel(k),labels)
            b.setIcon(self._icon('dot',qt.QColor.fromRgbF(*color).name()))
            b.setCheckable(True)
            b.setToolTip(name)
            self.labelButtons[key] = b
        lay.addLayout(labels)
        b = self._button('Uncertain area',lambda:self.setLabel('uncertain'),lay)
        b.setIcon(self._icon('dot',qt.QColor.fromRgbF(*LABELS['uncertain'][1]).name()))
        b.setCheckable(True)
        self.labelButtons['uncertain'] = b
        # Retained as an internal selection model for compatibility, not a hidden image layer.
        self.labelCombo = qt.QComboBox(panel)
        self.labelCombo.addItems([value[0] for value in LABELS.values()])
        self.labelCombo.hide()
        tools = qt.QHBoxLayout()
        self.toolButtons = {}
        for name in ['Paint','Draw','Erase']:
            b = qt.QToolButton()
            b.setText(name)
            b.setIcon(self._icon(name.lower()))
            b.setIconSize(qt.QSize(20,20))
            b.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon)
            b.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Fixed)
            b.setMinimumHeight(48)
            b.setCheckable(True)
            b.connect('clicked()',lambda n=name:self.setTool(n))
            tools.addWidget(b)
            self.toolButtons[name] = b
        lay.addLayout(tools)
        self.toolText = qt.QLabel('Choose a case to annotate')
        self.toolText.wordWrap = True
        self.toolText.setMinimumHeight(38)
        lay.addWidget(self.toolText)
        brush = qt.QHBoxLayout()
        brush.addWidget(qt.QLabel('Brush size'))
        self.brushSize = qt.QDoubleSpinBox()
        self.brushSize.setRange(.3,30)
        self.brushSize.setSingleStep(.5)
        self.brushSize.setSuffix(' mm')
        self.brushSize.setDecimals(1)
        self.brushSize.setValue(float(self.settings.value('Meniscus/brush',3)))
        self.brushSize.connect('valueChanged(double)',self._brush)
        brush.addWidget(self.brushSize,1)
        lay.addLayout(brush)
        history = qt.QHBoxLayout()
        self._button('Undo',self._undo,history,icon='undo')
        self._button('Redo',self._redo,history,icon='redo')
        lay.addLayout(history)
        display = ctk.ctkCollapsibleButton()
        display.text = 'Display and orientation'
        display.collapsed = True
        inner = qt.QVBoxLayout(display)
        inner.setContentsMargins(0,8,0,8)
        row = qt.QHBoxLayout()
        self.visible = qt.QCheckBox('Show annotation')
        self.visible.setChecked(True)
        self.visible.connect('toggled(bool)',self._display)
        row.addWidget(self.visible)
        self.fill = qt.QCheckBox('Fill')
        self.fill.setChecked(True)
        self.fill.connect('toggled(bool)',self._display)
        row.addWidget(self.fill)
        inner.addLayout(row)
        inner.addWidget(qt.QLabel('Fill opacity'))
        self.opacity = qt.QSlider(qt.Qt.Horizontal)
        self.opacity.setRange(0,100)
        self.opacity.setValue(25)
        self.opacity.connect('valueChanged(int)',self._display)
        inner.addWidget(self.opacity)
        self.windowLevelButton = self._button('Window/level',self._windowLevel,inner)
        self.windowLevelButton.setCheckable(True)
        self.windowLevelButton.setToolTip('Left-drag on the image to adjust brightness and contrast. Choose Paint, Draw or Erase to return to annotation.')
        self._button('Reset view',self._resetView,inner,icon='reset')
        self.reformats = qt.QCheckBox('Show orientation views')
        self.reformats.setToolTip('Coronal and axial reformats are for orientation. Editing stays on the acquired sagittal view.')
        self.reformats.connect('toggled(bool)',self._layoutViews)
        inner.addWidget(self.reformats)
        lay.addWidget(display)
        self._title('Slice review',lay)
        self.attention = qt.QCheckBox('Flag this slice')
        self.attention.connect('toggled(bool)',self._flag)
        lay.addWidget(self.attention)
        self.notes = qt.QTextEdit()
        self.notes.setPlaceholderText('Notes for this case or uncertain findings')
        self.notes.setFixedHeight(78)
        self.notes.connect('textChanged()',self._notesChanged)
        lay.addWidget(self.notes)
        review = ctk.ctkCollapsibleButton()
        review.text = 'Case review and protocol'
        review.collapsed = True
        self.caseReviewPanel = review
        reviewLay = qt.QVBoxLayout(review)
        reviewLay.setContentsMargins(0,8,0,8)
        self.medialConsidered = qt.QCheckBox('Medial compartment considered')
        self.lateralConsidered = qt.QCheckBox('Lateral compartment considered')
        for checkbox in [self.medialConsidered,self.lateralConsidered]:
            checkbox.connect('toggled(bool)',self._compartments)
            reviewLay.addWidget(checkbox)
        self.protocolLabel = qt.QLabel('Practice work · Draft protocol')
        self.protocolLabel.objectName = 'support'
        self.protocolLabel.wordWrap = True
        reviewLay.addWidget(self.protocolLabel)
        lay.addWidget(review)
        lay.addStretch(1)
        self.editor = slicer.qMRMLSegmentEditorWidget(panel)
        self.editor.setMRMLScene(slicer.mrmlScene)
        self.editor.setMaximumNumberOfUndoStates(30)
        self.editor.setUndoEnabled(True)
        self.editor.setEffectNameOrder(['Draw','Paint','Erase'])
        self.editor.unorderedEffectsVisible = False
        self.editor.autoShowSourceVolumeNode = False
        for method in ['setSourceVolumeNodeSelectorVisible','setSegmentationNodeSelectorVisible','setSwitchToSegmentationsButtonVisible','setShow3DButtonVisible']:
            if hasattr(self.editor,method): getattr(self.editor,method)(False)
        self.editor.hide()
        scroll = qt.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(qt.QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setStyleSheet(self.style)
        self.rightDock.setWidget(scroll)
        self.rightDock.setMinimumWidth(270)
        slicer.util.mainWindow().addDockWidget(qt.Qt.RightDockWidgetArea,self.rightDock)

    def _menu(self, button, actions):
        menu = qt.QMenu(button)
        menu.setStyleSheet(self.style)
        for text,callback,name in actions:
            if text is None:
                menu.addSeparator()
            else:
                action = menu.addAction(self._icon(name),text)
                action.connect('triggered()',callback)
        button.setMenu(menu)
        button.setPopupMode(qt.QToolButton.InstantPopup)
        return menu

    def _headerButton(self, text, icon):
        button = qt.QToolButton()
        button.setText(text)
        button.setIcon(self._icon(icon))
        button.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        button.setIconSize(qt.QSize(18,18))
        button.objectName = 'quiet'
        self.topBar.addWidget(button)
        return button

    def _buildBars(self):
        main = slicer.util.mainWindow()
        self.topBar = qt.QToolBar('Meniscus Annotator',main)
        self.topBar.objectName = 'MeniscusHeader'
        self.topBar.setMovable(False)
        self.topBar.setFont(self.font)
        self.topBar.setStyleSheet(self.style)
        title = qt.QLabel('Meniscus Annotator')
        title.objectName = 'appTitle'
        self.topBar.addWidget(title)
        self.casesToggle = self._headerButton('Cases','cases')
        self.casesToggle.setCheckable(True)
        self.casesToggle.setChecked(True)
        self.casesToggle.connect('toggled(bool)',self.caseListDock.setVisible)
        self.caseListDock.connect('visibilityChanged(bool)',self.casesToggle.setChecked)
        self.identityLabel = qt.QLabel('No case open')
        self.identityLabel.objectName = 'identity'
        self.topBar.addWidget(self.identityLabel)
        self.initializationLabel = qt.QLabel('')
        self.initializationLabel.objectName = 'initializationMode'
        self.initializationLabel.wordWrap = True
        self.topBar.addWidget(self.initializationLabel)
        spacer = qt.QWidget()
        spacer.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Preferred)
        self.topBar.addWidget(spacer)
        self.saveStatus = qt.QLabel('No case open')
        self.saveStatus.objectName = 'saveState'
        self.topBar.addWidget(self.saveStatus)
        dataset = self._headerButton('Dataset','folder')
        self._menu(dataset,[('Open dataset…',self._chooseDataset,'folder'),('Resume work',self._resume,'resume'),(None,None,None),('Show dataset folder',self._showDataset,'folder'),('Show saved work',self._showWork,'folder'),('Export results…',self._exportDialog,'export')])
        self.toolsToggle = self._headerButton('Tools','tools')
        self.toolsToggle.setCheckable(True)
        self.toolsToggle.setChecked(True)
        self.toolsToggle.connect('toggled(bool)',self.rightDock.setVisible)
        self.rightDock.connect('visibilityChanged(bool)',self.toolsToggle.setChecked)
        helpButton = self._headerButton('Help','help')
        self._menu(helpButton,[('Controls and shortcuts',self._help,'help'),('Annotation setup…',self._loadJob,'folder'),('Troubleshooting',self._diagnostics,'help'),('About Meniscus Annotator',self._about,'help')])
        main.addToolBar(qt.Qt.TopToolBarArea,self.topBar)
        self.bottomBar = qt.QToolBar('Acquired slices and review',main)
        self.bottomBar.objectName = 'MeniscusNavigation'
        self.bottomBar.setMovable(False)
        self.bottomBar.setFont(self.font)
        self.bottomBar.setStyleSheet(self.style)
        footer = qt.QWidget()
        footer.objectName = 'navigationPanel'
        footer.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Preferred)
        footerLayout = qt.QVBoxLayout(footer)
        footerLayout.setContentsMargins(2,2,2,2)
        footerLayout.setSpacing(10)
        nav = qt.QHBoxLayout()
        nav.setSpacing(12)
        self.sliceReadout = qt.QLabel('Slice — of —')
        self.sliceReadout.objectName = 'sliceReadout'
        self.sliceReadout.setMinimumWidth(148)
        nav.addWidget(self.sliceReadout)
        self.previousButton = self._button('Previous',lambda:self.goSlice(self.currentSlice-1),nav,icon='previous')
        self.sliceSlider = qt.QSlider(qt.Qt.Horizontal)
        self.sliceSlider.setRange(1,1)
        self.sliceSlider.setSingleStep(1)
        self.sliceSlider.setPageStep(1)
        self.sliceSlider.setMinimumWidth(160)
        self.sliceSlider.setToolTip('Every acquired slice, in source order. Displayed slice 1 is stored index 0.')
        self.sliceSlider.setAccessibleName('Acquired slice')
        self.sliceSlider.connect('valueChanged(int)',lambda value:self.goSlice(value-1))
        nav.addWidget(self.sliceSlider,1)
        self.nextButton = self._button('Next',lambda:self.goSlice(self.currentSlice+1),nav,icon='next')
        nav.addWidget(qt.QLabel('Go to'))
        self.sliceSpin = qt.QSpinBox()
        self.sliceSpin.setRange(1,1)
        self.sliceSpin.setMinimumWidth(64)
        self.sliceSpin.setAccessibleName('Go to acquired slice')
        self.sliceSpin.connect('valueChanged(int)',lambda value:self.goSlice(value-1))
        nav.addWidget(self.sliceSpin)
        footerLayout.addLayout(nav)
        self.actionBar = qt.QWidget()
        actions = qt.QHBoxLayout(self.actionBar)
        actions.setContentsMargins(0,0,0,0)
        actions.setSpacing(10)
        self.progress = qt.QLabel('No slices reviewed')
        self.progress.objectName = 'support'
        actions.addWidget(self.progress)
        jump = qt.QToolButton()
        jump.setText('Jump to')
        jump.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        jump.setIcon(self._icon('next'))
        self._menu(jump,[('Next unreviewed slice',self._nextUnreviewed,'next'),('Next flagged slice',self._nextFlagged,'flag')])
        actions.addWidget(jump)
        self.reviewButton = self._button('Mark reviewed and next',self._reviewNext,actions,True,icon='check')
        actions.addStretch(1)
        self.saveButton = self._button('Save draft',lambda:self._safe(self.save),actions,icon='save')
        self.approveButton = self._button('Approve case',self._approve,actions,icon='check')
        footerLayout.addWidget(self.actionBar)
        self.bottomBar.addWidget(footer)
        main.addToolBar(qt.Qt.BottomToolBarArea,self.bottomBar)

    def _finishLayout(self):
        main = slicer.util.mainWindow()
        for bar in main.findChildren(qt.QToolBar):
            if bar not in [self.topBar,self.bottomBar]: bar.hide()
        defaultPanel = main.findChild(qt.QDockWidget, 'PanelDockWidget')
        if defaultPanel:
            defaultPanel.hide()
        slicer.util.setApplicationLogoVisible(False)
        slicer.util.setModuleHelpSectionVisible(False)
        slicer.util.setDataProbeVisible(False)
        slicer.util.setPythonConsoleVisible(False)
        probe = getattr(slicer.modules,'DataProbeInstance',None)
        if probe and getattr(probe,'infoWidget',None):
            annotations = probe.infoWidget.sliceAnnotations
            annotations.sliceViewAnnotationsEnabled = False
            annotations.updateSliceViewFromGUI()
        main.menuBar().hide()
        main.statusBar().hide()
        main.setWindowTitle('Meniscus Annotator ' + VERSION)
        main.setMinimumSize(1024,700)
        main.setStyleSheet('QMainWindow { background:#101820; } QMainWindow::separator { background:#dce3e9; width:1px; height:1px; }')
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        for action in main.findChildren(qt.QAction):
            if not any(word in str(action.objectName) for word in ['Exit','Quit']): action.setShortcut(qt.QKeySequence())
        self._installShortcuts()
        main.resizeDocks([self.caseListDock,self.rightDock],[int(self.settings.value('Meniscus/casesWidth',270)),int(self.settings.value('Meniscus/toolsWidth',290))],qt.Qt.Horizontal)
        self._lockControllers()
        from MeniscusAnnotatorLib.interface import EmptyCanvas
        self.emptyCanvas = EmptyCanvas(slicer.app.layoutManager().sliceWidget('Red').sliceView(),self)
        self.emptyCanvas.ready(bool(self.dataset))

    def _updatePracticeContext(self):
        context = (self.session.state.get('practice_context') if self.session else None) or (getattr(self.store,'practice_context',None) if self.store else None)
        if context:
            automated = context.get('actor_type')=='automated'
            slicer.util.mainWindow().setWindowTitle('Meniscus Annotator — AUTOMATED SOFTWARE QA' if automated else 'Meniscus Annotator — SOFTWARE PRACTICE — not research annotations')
            self.protocolLabel.setText('SOFTWARE PRACTICE · Not accepted research annotations')
            self.message.setText('AUTOMATED SOFTWARE QA · Not human annotations' if automated else 'SOFTWARE PRACTICE · Separate work and exports')
        return context

    def _showDataset(self):
        if self.dataset: qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(self.dataset.root)))

    def _diagnostics(self):
        slicer.util.infoDisplay(self._diagnostic or 'No errors recorded in this session.',windowTitle='Troubleshooting — keep details private')

    def _about(self):
        notice = qt.QMessageBox(slicer.util.mainWindow())
        notice.setWindowTitle('About Meniscus Annotator')
        revision = (SOURCE_IDENTITY.get('application_commit') or 'unrecorded')[:12]
        if SOURCE_IDENTITY.get('application_source_dirty'):
            revision += ' · local changes'
        notice.setText('Meniscus Annotator ' + VERSION + '\nBuild: ' + revision + '\nSource: ' + SOURCE_IDENTITY['application_source_sha256'][:12] + '\nResearch annotation of acquired knee MRI.\n\nRuntime: 3D Slicer ' + slicer.app.applicationVersion + '. The Slicer runtime and third-party licences and attributions remain part of this distribution.')
        upstream = notice.addButton('About 3D Slicer',qt.QMessageBox.ActionRole)
        notice.addButton(qt.QMessageBox.Close)
        notice.exec_()
        if notice.clickedButton()==upstream:
            action = slicer.util.mainWindow().findChild(qt.QAction,'HelpAboutSlicerAction')
            if action: action.trigger()

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
            self.message.setText('Action failed. Previous saved versions are intact.')
            self.saveStatus.setText('Action failed · check details')
            advice = ('\n\nContact the dataset coordinator if the input or saved-work configuration needs correction. Diagnostic details are available in Help.'
                      if isinstance(exc, ValidationError) else
                      '\n\nCheck the work location, available disk space and permissions, then retry. Diagnostic details are available in Help.')
            slicer.util.errorDisplay(reason + advice, windowTitle='Meniscus annotation')
            return None

    def _chooseReaderIdentity(self, previous=''):
        dialog = qt.QDialog(slicer.util.mainWindow())
        dialog.objectName = 'MeniscusReaderIdentityDialog'
        dialog.setWindowTitle('Reader identity')
        layout = qt.QVBoxLayout(dialog)
        explanation = qt.QLabel('Enter the name or study ID to record with your corrections. Use your own identity. Each reader’s work is kept separately.')
        explanation.wordWrap = True
        layout.addWidget(explanation)
        layout.addWidget(qt.QLabel('Reader name or study ID'))
        entry = qt.QLineEdit()
        entry.objectName = 'MeniscusReaderIdentityInput'
        entry.setPlaceholderText('Enter your name or assigned reader ID')
        entry.setText(previous)
        layout.addWidget(entry)
        buttons = qt.QDialogButtonBox()
        proceed = buttons.addButton('Continue', qt.QDialogButtonBox.AcceptRole)
        proceed.objectName = 'MeniscusReaderIdentityContinue'
        buttons.addButton('Cancel', qt.QDialogButtonBox.RejectRole)
        proceed.setEnabled(bool(str(entry.text).strip()))
        entry.connect('textChanged(QString)', lambda text: proceed.setEnabled(bool(str(text).strip())))
        buttons.connect('accepted()', dialog.accept)
        buttons.connect('rejected()', dialog.reject)
        layout.addWidget(buttons)
        entry.setFocus()
        entry.selectAll()
        if dialog.exec_() != qt.QDialog.Accepted:
            return None
        reader = str(entry.text).strip()
        return reader or None

    def _confirmDatasetStart(self, job, previous_reader=''):
        """Confirm intentional blank work and the assigned reader before writing work."""
        self._confirmedReader = None
        if (job or {}).get('practice_context'):
            # These fixed jobs already explicitly identify software-practice actors.
            return True
        if job is None:
            dialog = qt.QMessageBox(slicer.util.mainWindow())
            dialog.objectName = 'MeniscusBlankStartDialog'
            dialog.setWindowTitle('No starting masks configured')
            dialog.setText('This package opens with empty labels for drawing from scratch.')
            dialog.setInformativeText('If you expected existing automated masks to correct, choose No and obtain the correction package. Start blank annotation intentionally?')
            dialog.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
            dialog.setDefaultButton(qt.QMessageBox.No)
            if dialog.exec_() != qt.QMessageBox.Yes:
                return False
        from MeniscusAnnotatorLib.core import assigned_annotator
        actor = assigned_annotator(job)
        if actor is None:
            self._confirmedReader = self._chooseReaderIdentity(previous_reader)
            return self._confirmedReader is not None
        dialog = qt.QMessageBox(slicer.util.mainWindow())
        dialog.objectName = 'MeniscusReaderConfirmDialog'
        dialog.setWindowTitle('Confirm assigned reader')
        dialog.setText('This annotation job records work under: ' + actor)
        dialog.setInformativeText('Continue only if this is your assigned reader identity. Software testing must use a separate practice job. A coordinator must supply a different named job for another reader. Are you the assigned reader?')
        dialog.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        dialog.setDefaultButton(qt.QMessageBox.No)
        confirmed = dialog.exec_() == qt.QMessageBox.Yes
        if confirmed:
            self._confirmedReader = actor
        return confirmed

    def _chooseDataset(self):
        root = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Open dataset', str(self.settings.value('Meniscus/dataset', '')))
        if root:
            self._safe(lambda: self.openDataset(root))

    def openDataset(self, root, work_root=None):
        if self._practiceConfig and Path(root).resolve()!=Path(self._practiceConfig['input_root']).resolve():
            raise ValidationError('This software-practice launcher is restricted to its two permitted cases. Other datasets cannot be opened here.')
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
        job_path = str(self.settings.value('Meniscus/job/' + ds.identity, ''))
        fixed_job = self._practiceConfig['job_path'] if self._practiceConfig else None
        job, job_path = load_dataset_job_config(ds, remembered_path=job_path, fixed_job_path=fixed_job)
        if self._practiceConfig and (not job or job.get('practice_context',{}).get('purpose')!='software_practice'):
            raise ValidationError('The software-practice actor and protocol configuration is missing or invalid.')
        from MeniscusAnnotatorLib.core import canonical
        source_job = getattr(job, 'source_job', job)
        reader_key = 'Meniscus/reader/' + ds.identity + '/' + (canonical(source_job) if source_job else 'blank')
        if not self._confirmDatasetStart(job, str(self.settings.value(reader_key, ''))):
            self.message.setText('Opening cancelled. No new annotation work was created.')
            return None
        from MeniscusAnnotatorLib.reader_workspace import reader_workspace
        reader = self._confirmedReader
        workspace = reader_workspace(version, job, reader=reader)
        remembered = self.settings.value(workspace['settings_key'], '')
        location = work_root or (self._practiceConfig['work_root'] if self._practiceConfig else remembered) or str(Path(documents) / 'Meniscus_annotation_work' / workspace['relative_folder'])
        if self._practiceConfig and Path(location).resolve()!=Path(self._practiceConfig['work_root']).resolve():
            raise ValidationError('Software practice must use its separate local practice work folder.')
        if not work_root and not remembered and not self._practiceConfig:
            dialog = qt.QMessageBox(slicer.util.mainWindow())
            dialog.setWindowTitle('Local work folder')
            dialog.setText('Annotations will be saved separately from the dataset.')
            dialog.setInformativeText(str(location))
            use = dialog.addButton('Use this folder', qt.QMessageBox.AcceptRole)
            change = dialog.addButton('Change location', qt.QMessageBox.ActionRole)
            existing = dialog.addButton('Open existing work', qt.QMessageBox.ActionRole)
            cancel = dialog.addButton('Cancel', qt.QMessageBox.RejectRole)
            dialog.exec_()
            clicked = dialog.clickedButton()
            if clicked in (None, cancel):
                return
            if clicked == existing:
                chosen = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Open existing work folder', documents)
                if not chosen:
                    return
                if not (Path(chosen) / 'dataset.json').is_file():
                    raise ValidationError('Select the saved work folder containing dataset.json and cases. The dataset folder contains the original scans, not saved work.')
                location = str(chosen)
            elif clicked == change:
                chosen = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Choose local work folder', documents)
                if not chosen:
                    return
                location = str(Path(chosen) / workspace['relative_folder'])
        store = WorkStore(location, ds, job=job, reader=reader)
        self.closeCase()
        self.dataset, self.store = ds, store
        self._lastCaseSettingsKey = workspace['settings_key'] + '/lastCase' if workspace['uses_local_reader_assignment'] else 'Meniscus/lastCase'
        self._updatePracticeContext()
        self.settings.setValue('Meniscus/dataset', str(Path(root).resolve()))
        self.settings.setValue(workspace['settings_key'], str(location))
        if workspace['uses_local_reader_assignment']:
            self.settings.setValue(reader_key, reader)
        blocked = sum(rule.get('availability') == 'unresolved' for rule in (job or {}).get('cases', {}).values())
        self.datasetLabel.setText(version + '\nReader: ' + store.annotator + '\n' + str(len(ds.cases)) + ' MRI scans' + (f' · {blocked} blocked' if blocked else '') + ' · local work connected')
        self._populate()
        if self.caseTable.rowCount:
            self.caseTable.selectRow(0)
        self.message.setText('Dataset ready. Select a case to begin.')
        if getattr(self,'emptyCanvas',None): self.emptyCanvas.ready(True)
        return ds

    def _loadJob(self):
        if self._practiceConfig:
            slicer.util.infoDisplay('This launcher uses a fixed SOFTWARE PRACTICE protocol and separate work folder. Research jobs cannot be loaded here.',windowTitle='Software practice only')
            return
        if not self.dataset:
            slicer.util.warningDisplay('Open the dataset first.')
            return
        path = qt.QFileDialog.getOpenFileName(slicer.util.mainWindow(), 'Load explicit annotation job', '', 'JSON configuration (*.json)')
        if not path:
            return
        def load():
            require_full = (self.dataset.root / 'correction_job.json').exists() or correction_inputs_present(self.dataset) or Path(path).name == 'correction_job.json'
            job = load_job_config(path, self.dataset, require_full_correction=require_full, allow_unresolved=True)
            if not self._confirmDatasetStart(job, self.store.annotator):
                return
            self.closeCase()
            self.store = WorkStore(self.store.root, self.dataset, job=job, reader=self._confirmedReader)
            self.settings.setValue('Meniscus/job/' + self.dataset.identity, str(path))
            self.message.setText('Explicit job loaded. Open a case; only permitted starting masks will be loaded.')
        self._safe(load)

    def _populate(self):
        if not self.dataset:
            return
        self.caseTable.setRowCount(len(self.dataset.cases))
        for row, case in enumerate(self.dataset.cases):
            m = case.metadata
            identity = f"{m['participant_id']}\nM{int(m['visit_month']):03d} · {'Left' if m['knee_side']=='L' else 'Right'}"
            item = qt.QTableWidgetItem(identity)
            item.setData(qt.Qt.UserRole, case.key)
            self.caseTable.setItem(row, 0, item)
            status = 'Not started'
            rule = (self.store.job or {}).get('cases', {}).get(case.key, {})
            if rule.get('availability') == 'unresolved':
                status = 'Blocked'
                item.setToolTip(str(rule.get('reason', 'Starting mask unresolved')))
            elif self.session and self.session.case.key == case.key:
                status = 'Approved' if self.session.state.get('status') in ('approved', 'practice_approved') else ('Needs review' if any(not r['reviewed'] for r in self.session.state['review']) else 'In progress')
            elif hasattr(self.store, 'summary'):
                summary = self.store.summary(case)
                status = {'approved':'Approved', 'practice_approved':'Approved', 'not_started':'Not started', 'needs_review':'Needs review', 'in_progress':'In progress', 'saved_unavailable':'Saved work needs attention', 'configuration_mismatch':'Saved work needs attention'}.get(summary.get('status'), 'In progress')
            progressItem = qt.QTableWidgetItem(status)
            self.caseTable.setItem(row,1,progressItem)
            if self.session and case.key==self.session.case.key:
                self.caseTable.selectRow(row)
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
        key = str(self.settings.value(getattr(self, '_lastCaseSettingsKey', 'Meniscus/lastCase'), ''))
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
        self.sliceReadout.setText('Slice — of —')
        self.identityLabel.setText('No case open')
        self.initializationLabel.setText('')
        self.saveStatus.setText('No case open')
        if getattr(self,'emptyCanvas',None): self.emptyCanvas.ready(bool(self.dataset))

    def openCase(self, key):
        if self.session and self.session.case.key == key:
            return
        from MeniscusAnnotatorLib.core import require_case_prediction_available
        require_case_prediction_available(self.store.job, key)
        self.closeCase()
        case = next(c for c in self.dataset.cases if c.key == key)
        self.session = self.store.open_case(case)
        if getattr(self,'emptyCanvas',None): self.emptyCanvas.hide()
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
            self.sliceSlider.setMaximum(case.n_slices)
            self.notes.setPlainText(self.session.state.get('notes', ''))
            self.medialConsidered.setChecked(self.session.state['compartments']['medial'])
            self.lateralConsidered.setChecked(self.session.state['compartments']['lateral'])
            self.protocolLabel.setText('Practice work · Draft protocol' if self.session.state['protocol']['status']=='draft' else 'Protocol ' + self.session.state['protocol']['version'])
            self.dirty = False
            self._enable(True)
            self.setLabel('medial')
            self.setTool('Paint')
            self.settings.setValue(getattr(self, '_lastCaseSettingsKey', 'Meniscus/lastCase'), key)
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
        # Use a superior-up display while retaining the acquired-plane normal and
        # original IJK grid. This is an in-plane 180-degree camera rotation only.
        if up[2] < 0:
            up = -up
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
                # Fit resets the slice position to the volume centre. Keep its
                # field of view, then restore this requested acquired plane.
                for i in range(3):
                    mat.SetElement(i,3,float(centre[i]))
                node.UpdateMatrices()
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
        if self._windowLevelActive:
            self.setTool('Paint')
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
        self._windowLevelActive = False
        self.windowLevelButton.setChecked(False)
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)
        self.editor.setActiveEffectByName(name)
        self._configureEffects()
        for n, b in self.toolButtons.items():
            b.setChecked(n == name)
        self._toolStatus()

    def _windowLevel(self):
        if not self.session:
            return
        if self._windowLevelActive:
            self.setTool('')
            return
        self._segmentChanged()
        self.editor.setActiveEffectByName('')
        self._windowLevelActive = True
        for button in self.toolButtons.values(): button.setChecked(False)
        self.windowLevelButton.setChecked(True)
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.AdjustWindowLevel)
        self._toolStatus()

    def _toolStatus(self):
        if self._windowLevelActive:
            self.toolText.setText('Window/level · Display only\nLeft-drag to adjust brightness and contrast')
            annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
            annotation.SetText(vtk.vtkCornerAnnotation.UpperRight,'Window/level · Display only\nLeft-drag · No drawing')
            slicer.app.layoutManager().sliceWidget('Red').sliceView().forceRender()
            return
        tool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Navigate'
        self.toolText.setText(f'{LABELS[self.activeLabel][0]} · {tool}\nEditing: this acquired slice only')
        annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
        annotation.SetText(vtk.vtkCornerAnnotation.UpperRight,f'{LABELS[self.activeLabel][0]} · {tool}\n{self.brushSize.value:g} mm · This slice only')
        slicer.app.layoutManager().sliceWidget('Red').sliceView().forceRender()

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
        # Keep the acquired plane dominant; orientation reformats occupy a narrow column.
        layout_id = 703
        description = '<layout type="horizontal"><item splitSize="700"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Sagittal</property></view></item><item splitSize="300"><layout type="vertical"><item><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Coronal</property></view></item><item><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Axial</property></view></item></layout></item></layout>'
        if not getattr(self,'_orientationLayoutAdded',False):
            lm.layoutLogic().GetLayoutNode().AddLayoutDescription(layout_id,description)
            self._orientationLayoutAdded = True
        k = self.currentSlice
        self._snap = True
        try:
            lm.setLayout(layout_id if self.reformats.checked else slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
            self._lockControllers()
            if self.volume:
                slicer.util.setSliceViewerLayers(background=self.volume)
                lm.sliceWidget('Yellow').mrmlSliceNode().SetOrientationToCoronal() if lm.sliceWidget('Yellow') else None
                lm.sliceWidget('Green').mrmlSliceNode().SetOrientationToAxial() if lm.sliceWidget('Green') else None
        finally:
            self._snap = False
        if self.volume:
            self._nativePlane(k)
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
        correction = self.session.state['initialization']['method'] == 'correction'
        self.initializationLabel.setText('Correction · Existing automated mask' if correction else 'Blank annotation · No starting mask')
        self.initializationLabel.setToolTip('Starting masks are unreviewed model predictions. Check both compartments throughout the acquired stack.' if correction else 'This case was intentionally initialized with empty labels.')
        review = self.session.state['review']
        count = sum(bool(r['reviewed']) for r in review)
        flags = sum(bool(r['flag']) for r in review)
        self.progress.setText(f'{count} of {len(review)} reviewed · {flags} flagged')
        self.sliceReadout.setText(f'Slice {self.currentSlice+1} of {len(review)}')
        self.sliceSlider.blockSignals(True)
        self.sliceSlider.setValue(self.currentSlice+1)
        self.sliceSlider.blockSignals(False)
        self.previousButton.setEnabled(self.currentSlice>0)
        self.nextButton.setEnabled(self.currentSlice<len(review)-1)
        self.sliceSpin.blockSignals(True)
        self.sliceSpin.setValue(self.currentSlice+1)
        self.sliceSpin.blockSignals(False)
        self.attention.blockSignals(True)
        self.attention.setChecked(review[self.currentSlice]['flag'])
        self.attention.blockSignals(False)
        state = 'Reviewed' if review[self.currentSlice]['reviewed'] else 'Not reviewed'
        context = self._updatePracticeContext()
        save_text = 'Unsaved changes' if self.dirty else ('Saved' if self.session.current_checkpoint else 'New draft')
        self.saveStatus.setText(('SOFTWARE PRACTICE · ' if context else '') + save_text)
        if not context:
            self.message.setText('Practice work · Draft protocol' if self.session.state['protocol']['status']=='draft' else 'Protocol ' + self.session.state['protocol']['version'])
        annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
        annotation.SetText(vtk.vtkCornerAnnotation.UpperLeft,f'Slice {self.currentSlice+1} of {len(review)}\n{state}')

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
        self.saveStatus.setText(('SOFTWARE PRACTICE · ' if self.session.state.get('practice_context') else '') + 'Saving…')
        self.saveStatus.repaint()
        labels, uncertain = self.collectArrays()
        self.session.state['runtime'] = {'slicer_version':slicer.app.applicationVersion, 'slicer_revision':slicer.app.repositoryRevision, 'application_version':VERSION, 'interface_revision':'workspace-2', **SOURCE_IDENTITY}
        path = self.session.save(labels, uncertain, self._segWriter, approve=approve, practice=practice)
        self.dirty = False
        self.refreshReview()
        self._populate()
        self.saveStatus.setText(('SOFTWARE PRACTICE · ' if self.session.state.get('practice_context') else '') + (('Practice approved · Saved' if practice else 'Approved · Saved') if approve else 'Saved'))
        return path

    def _approve(self):
        if not self.session:
            return
        practice = self.session.state['protocol']['status'] == 'draft'
        labels, uncertain = self.collectArrays()
        errors = self.session.approval_errors(labels, uncertain, practice=practice)
        if errors:
            self.caseReviewPanel.collapsed = False
            slicer.util.warningDisplay('Approval is unavailable:\n\n' + '\n'.join('• ' + e for e in errors),windowTitle='Review required')
            return
        context = self.session.state.get('practice_context')
        if context:
            text = 'SOFTWARE PRACTICE ONLY. This records completion of a practice workflow, not an accepted research annotation or anatomical validation.\n\nRecorded practice actor: ' + self.session.state['annotator'] + '. Automated checks are not attributed to a reader.\n\nRecord this practice version?'
        else:
            actor = self.session.state['annotator']
            text = ('This protocol is a draft. This creates an approved PRACTICE version, excluded from research exports.\n\n' if practice else '') + 'I, ' + actor + ', have considered both compartments and reviewed every acquired slice under the recorded protocol. This is my own approval, not an independent second-reader assessment.\n\nApprove this version?'
        if slicer.util.confirmYesNoDisplay(text,windowTitle='Approve case'):
            self._safe(lambda: self.save(approve=True,practice=practice))

    def _nextCase(self):
        if self.dataset:
            index = next((i for i,c in enumerate(self.dataset.cases) if self.session and c.key==self.session.case.key), -1)
            rules = (self.store.job or {}).get('cases', {})
            for offset in range(1, len(self.dataset.cases) + 1):
                case = self.dataset.cases[(index + offset) % len(self.dataset.cases)]
                if rules.get(case.key, {}).get('availability') != 'unresolved':
                    self._safe(lambda: self.openCase(case.key))
                    return
            self.message.setText('No available case. All starting masks are blocked.')

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
        dialog.setObjectName('MeniscusExportDialog')
        dialog.setWindowTitle('Export results')
        layout = qt.QVBoxLayout(dialog)
        layout.addWidget(qt.QLabel('Export verified approved checkpoints without MRI images.'))
        selected = qt.QCheckBox('Selected cases only (' + str(len(chosen_keys)) + ')')
        selected.setObjectName('MeniscusExportSelectedOnly')
        selected.setEnabled(bool(chosen_keys))
        layout.addWidget(selected)
        practice = qt.QCheckBox('Practice results (separate from research approval)')
        practice.setObjectName('MeniscusExportPractice')
        if getattr(self.store,'practice_context',None):
            practice.setText('SOFTWARE PRACTICE results only — not research annotations')
            practice.setChecked(True)
            practice.setEnabled(False)
        layout.addWidget(practice)
        # PythonQt can resolve the single integer argument as an orientation,
        # leaving the box empty. Set standard buttons explicitly after parenting.
        buttons = qt.QDialogButtonBox(dialog)
        buttons.setObjectName('MeniscusExportButtons')
        buttons.setStandardButtons(qt.QDialogButtonBox.Ok | qt.QDialogButtonBox.Cancel)
        export_button = buttons.button(qt.QDialogButtonBox.Ok)
        export_button.setObjectName('MeniscusExportConfirm')
        export_button.setText('Export')
        export_button.setDefault(True)
        buttons.button(qt.QDialogButtonBox.Cancel).setObjectName('MeniscusExportCancel')
        buttons.connect('accepted()',dialog.accept)
        buttons.connect('rejected()',dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != qt.QDialog.Accepted:
            return
        if self.session and self.dirty and self._safe(self.save) is None:
            return
        documents = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
        if self._practiceConfig:
            destination = Path(self._practiceConfig['results_root'])
        else:
            target = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Export results to folder', documents)
            if not target:
                return
            destination = Path(target)/'Meniscus_annotation_results'
        keys = None
        if selected.checked:
            keys = chosen_keys
        result = self._safe(lambda: export_approved(self.store, destination, case_keys=keys, include_practice=practice.checked))
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
        text = 'Meniscus Annotator ' + VERSION + '\n\nOpen dataset → Open case → Draw → Review every slice → Save draft → Approve → Export.\n\nMRI view shortcuts (inactive while typing notes):\nLeft / Right: acquired slice · R: reviewed and next\nU: next unreviewed · F: next flagged\n1 / 2 / 3: medial / lateral / uncertain\nP / D / E: paint / draw / erase · Esc: navigate\nCtrl+S: save · Ctrl+Z / Ctrl+Y: undo / redo\n\nNative Slicer mouse controls:\nCtrl+wheel: zoom · middle drag: pan\nRight drag: zoom · wheel: slice\nWindow/level: choose it in Display and orientation, then left-drag\nDraw: left-click contour points, right-click to apply.\n\nEvery changed slice requires review again. Uncertainty is a separate overlapping mask and blocks approval until resolved. Draft protocols allow practice approval only. Saved versions recover work after restart; in-memory undo history does not survive restart.\n\nHelp → Diagnostics includes details of the last error.'
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
        self.settings.setValue('Meniscus/casesWidth',self.caseListDock.width)
        self.settings.setValue('Meniscus/toolsWidth', self.rightDock.width)
        self.settings.sync()

    def cleanup(self):
        self._loading = True  # Native editing libraries may already be unloading; close guards saved beforehand.
        self.dirty = False  # aboutToQuit/close guard saves while native modules are still alive.
        if hasattr(self, 'autosave'):
            self.autosave.stop()
        self.closeCase()
        for name in ['caseListDock','rightDock','topBar','bottomBar']:
            widget = getattr(self, name, None)
            if widget:
                widget.hide()
                widget.deleteLater()
