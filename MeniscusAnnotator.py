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
from MeniscusAnnotatorLib.core import load_job_config, load_dataset_job_config, correction_inputs_present, export_plan, status_label, annotation_purpose, research_eligible, work_location_problem
from MeniscusAnnotatorLib.presentation import acquired_display_frame, slice_direction, label_plausibility
from MeniscusAnnotatorLib.build_identity import capture_source_identity
from MeniscusAnnotatorLib.regions import (REGIONS, initialize as initialize_regions,
                                         reconcile as reconcile_regions,
                                         invalidate_review as invalidate_regional_review)

VERSION = '0.2.0'
SOURCE_IDENTITY = capture_source_identity()
LABELS = {'medial': ('Medial meniscus', (0.30, 0.78, 0.92)),
          'lateral': ('Lateral meniscus', (0.95, 0.64, 0.31)),
          'uncertain': ('Uncertain area', (0.76, 0.56, 0.88))}
REGIONAL_COLORS = ((0.20, 0.75, 0.86), (0.15, 0.53, 0.68), (0.45, 0.88, 0.95),
                   (0.98, 0.69, 0.28), (0.84, 0.43, 0.12), (1.00, 0.82, 0.46))
REGIONAL_LABELS = {item['id']:(item['name'], REGIONAL_COLORS[index]) for index,item in enumerate(REGIONS)}
REGIONAL_LABELS['regional_uncertain'] = ('Boundary uncertain', (0.76, 0.56, 0.88))


class CloseGuard(qt.QObject):
    def __init__(self, workflow):
        super().__init__(slicer.util.mainWindow())
        self.workflow = workflow

    def eventFilter(self, watched, event):
        if event.type() == qt.QEvent.Quit and self.workflow._pendingDraw():
            if not self.workflow._resolveContourForClose():
                event.ignore()
                return True
        if event.type() == qt.QEvent.Close and watched == slicer.util.mainWindow() and self.workflow.dataset:
            try:
                # Complete storage while native modules still exist, before Qt teardown.
                if not self.workflow._resolveContourForClose() or self.workflow.closeCase() is False:
                    event.ignore()
                    return True
            except Exception as exc:
                self.workflow._diagnostic = traceback.format_exc()
                slicer.util.errorDisplay('The case could not be saved. Check available disk space and work-folder permissions, then retry Save draft. The application will stay open.\n\n' + str(exc), windowTitle='Save required before closing')
                event.ignore()
                return True
            event.ignore()
            qt.QTimer.singleShot(0, lambda: slicer.app.exit(0))
            return True
        return False


class WorkspaceLayoutObserver(qt.QObject):
    """Adapt secondary chrome without changing the native image view."""
    def __init__(self, workflow):
        super().__init__(slicer.util.mainWindow())
        self.workflow = workflow

    def eventFilter(self, watched, event):
        if event.type() == qt.QEvent.Resize and watched == slicer.util.mainWindow():
            self.workflow._adaptWorkspace()
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
        self.annotationTask = 'whole'
        self.activeRegion = 'anterior'
        self._regionBoundary = False
        self._lastCompartment = 'medial'
        self.regionalState = None
        self._lastRegionalArrays = None
        self.dirty = False
        self._updating = False
        self._loading = False
        self._snap = False
        self._observers = []
        self._lastArrays = None
        self._editQueued = False
        self._windowLevelActive = False
        self._drawContext = None
        self._drawHint = ''
        self._workflowHint = ''
        self._drawState = None
        self._drawMarkers = None
        self._drawObserverTags = {}
        self._rightDrawStart = None
        self._rightDrawDragged = False
        self._startingMaskSlices = None
        self._lastExport = None
        self._diagnostic = ''
        self._transferNotice = ''
        self._transferToken = 0
        self._plausibility = None
        self._closingContourDialog = False
        self._reviewOnlyDirty = False
        self._saveError = False
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
        self.drawFeedback = qt.QTimer()
        self.drawFeedback.setInterval(120)
        self.drawFeedback.connect('timeout()', self._pollDrawState)
        self.drawFeedback.start()
        self.closeGuard = CloseGuard(self)
        slicer.util.mainWindow().installEventFilter(self.closeGuard)
        slicer.app.installEventFilter(self.closeGuard)
        slicer.app.connect('aboutToQuit()', self._quit)
        self._enable(False)
        qt.QTimer.singleShot(0, self._finishLayout)

    def _buildStyle(self):
        from MeniscusAnnotatorLib.interface import icon, checkmark_path, down_arrow_path, ChoiceStrip, WheelGuard
        self._choiceStrip = ChoiceStrip
        self._wheelGuardClass = WheelGuard
        self._icon = icon
        families = list(qt.QFontDatabase().families())
        if sys.platform == 'win32':
            family = 'Segoe UI Variable' if 'Segoe UI Variable' in families else 'Segoe UI'
        else:
            family = qt.QFontDatabase.systemFont(qt.QFontDatabase.GeneralFont).family()
        self.font = qt.QFont(family, 11)
        self.font.setWeight(qt.QFont.Normal)
        self.font.setBold(False)
        self.parent.setFont(self.font)
        # Keep native menus, message boxes and scrollbars readable even when
        # the operating system/Slicer preference is dark. MRI pixels stay dark.
        palette = qt.QPalette()
        for role,color in [(qt.QPalette.Window,'#e9edf0'),(qt.QPalette.Base,'#fafbfc'),
                           (qt.QPalette.AlternateBase,'#edf0f2'),(qt.QPalette.Button,'#e5ebef'),
                           (qt.QPalette.WindowText,'#293842'),(qt.QPalette.Text,'#293842'),
                           (qt.QPalette.ButtonText,'#293842'),(qt.QPalette.Highlight,'#246d98'),
                           (qt.QPalette.HighlightedText,'#ffffff')]:
            palette.setColor(role,qt.QColor(color))
        for role in (qt.QPalette.WindowText,qt.QPalette.Text,qt.QPalette.ButtonText):
            palette.setColor(qt.QPalette.Disabled,role,qt.QColor('#7b8993'))
        slicer.app.setPalette(palette)
        self._lightPalette = palette
        self.style = '''
        QWidget { color:#293842; font-size:11pt; font-weight:normal; }
        QWidget#workspacePanel { background:#e9edf0; }
        QWidget#navigationPanel, QToolBar { background:#edf0f2; border:0; }
        QToolBar { spacing:8px; padding:4px 10px; border-bottom:1px solid #cbd3d9; }
        QDockWidget { background:#e9edf0; border:0; }
        QLabel { background:transparent; }
        QLabel#appTitle { font-size:12pt; font-weight:500; color:#263842; padding-right:8px; }
        QLabel#identity { font-size:11pt; font-weight:500; color:#263842; }
        QLabel#panelTitle { font-size:11pt; font-weight:500; padding:2px 0; }
        QLabel#support { color:#52636f; }
        QLabel#sliceReadout { font-size:11pt; font-weight:500; color:#263842; }
        QLabel#saveState { padding:0 4px; }
        QLabel#MeniscusInstruction { color:#3b505f; }
        QWidget#toolStrip { background:#dfe5e9; border-radius:3px; }
        QPushButton, QToolButton { background:transparent; border:1px solid transparent; border-radius:3px; min-height:24px; padding:3px 7px; font-weight:normal; }
        QPushButton:hover, QToolButton:hover { background:#dce4ea; border-color:#b8c8d3; }
        QPushButton:checked, QToolButton:checked { background:#d7e8f4; border:1px solid #2874a0; color:#174f70; }
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:2px solid #2874a0; }
        QPushButton:disabled, QToolButton:disabled { color:#7b8993; background:transparent; border-color:transparent; }
        QPushButton#primary { background:#246d98; color:white; border-color:#246d98; }
        QPushButton#primary:hover { background:#195a80; }
        QPushButton#primary:disabled { color:#75828d; background:#d9e0e5; border-color:#d9e0e5; }
        QPushButton#quiet, QToolButton#quiet { border-color:transparent; background:transparent; }
        QPushButton#quiet:hover, QToolButton#quiet:hover { background:#dce4ea; }
        QToolButton#quiet:checked { background:#d7e8f4; border-color:#8ab0c9; color:#174f70; }
        QPushButton#quiet:focus, QToolButton#quiet:focus { border:2px solid #2874a0; }
        QPushButton#saveDraft { border-color:#aebdc8; background:#e4eaf0; }
        QPushButton#saveDraft:hover { background:#d7e3ec; border-color:#7c9ab0; }
        QToolButton#drawingTool { padding:3px 5px; min-height:24px; }
        QToolButton[preferredTool=true] { font-weight:500; }
        QPushButton[primaryStep=true] { background:#246d98; color:white; border-color:#246d98; }
        QPushButton[primaryStep=true]:hover { background:#195a80; }
        QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#7b8993; background:#e0e5e9; border-color:#cbd3d9; }
        QComboBox::drop-down { width:24px; border-left:1px solid #bdc8d0; background:#e5ebef; }
        QComboBox::down-arrow { image:url(DOWNARROW); width:14px; height:14px; }
        QComboBox QAbstractItemView { background:#fafbfc; color:#293842; selection-background-color:#246d98; selection-color:white; outline:0; }
        QComboBox QAbstractItemView::item { min-height:28px; padding:4px 8px; }
        QPushButton[choice=true] { background:#e2e8ec; border:1px solid #b9c6ce; padding:3px 4px; min-height:26px; }
        QPushButton[choice=true]:checked { background:#d7e8f4; border-color:#2874a0; color:#174f70; }
        QPushButton[choice=true]:disabled { background:#e0e5e9; color:#7b8993; border-color:#cbd3d9; }
        QToolBar#MeniscusNextStep { background:#e6edf2; border-top:1px solid #cbd3d9; }
        QLabel#nextStep { color:#293842; }
        QScrollBar:vertical { background:#e2e8ec; width:12px; margin:0; }
        QScrollBar::handle:vertical { background:#9aaab6; min-height:28px; border-radius:4px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:#e2e8ec; }
        QMessageBox, QDialog { background:#edf0f2; color:#293842; }
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#fafbfc; border:1px solid #bdc8d0; border-radius:3px; padding:4px; min-height:22px; selection-background-color:#c9e0f0; selection-color:#203340; font-weight:normal; }
        QTableWidget { background:#edf0f2; alternate-background-color:#e9edf0; color:#293842; border:0; gridline-color:#dce3e8; selection-background-color:#d4e6f3; selection-color:#203340; }
        QHeaderView::section { background:#e9edf0; color:#52636f; border:0; border-bottom:1px solid #cbd3d9; padding:5px; font-size:11pt; font-weight:normal; }
        QCheckBox { background:transparent; spacing:7px; min-height:24px; font-weight:normal; }
        QCheckBox::indicator { width:16px; height:16px; background:#fafbfc; border:1px solid #8a9ba8; border-radius:3px; }
        QCheckBox::indicator:checked { background:#246d98; border-color:#246d98; image:url(CHECKMARK); }
        QCheckBox::indicator:disabled { border-color:#cbd3d9; background:#e8edf0; }
        QSlider::groove:horizontal { height:5px; background:#cfd9e1; border-radius:2px; }
        QSlider::sub-page:horizontal { background:#82afca; border-radius:2px; }
        QSlider::handle:horizontal { background:#246d98; border:2px solid #ffffff; width:16px; height:16px; margin:-7px 0; border-radius:8px; }
        QSlider::handle:horizontal:focus { border:2px solid #163f59; }
        QSlider::groove:horizontal:disabled { background:#dfe5e9; }
        QSlider::handle:horizontal:disabled { background:#aebcc6; }
        ctkCollapsibleButton { background:#e9edf0; color:#3b505f; border:0; border-top:1px solid #cbd3d9; padding:5px 0; text-align:left; font-weight:normal; }
        QMenu { background:#ffffff; color:#263642; border:1px solid #c4ced7; padding:5px; }
        QMenu::item { padding:7px 20px 7px 9px; }
        QMenu::item:selected { background:#dfedf7; }
        '''.replace('CHECKMARK', checkmark_path()).replace('DOWNARROW',down_arrow_path())
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
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
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
        self.progressFilter.addItems(['All cases', 'Not started', 'In progress', 'Needs review', 'Ready for approval', 'Practice approved', 'Research approved', 'Blocked', 'Saved work needs attention'])
        self.progressFilter.connect('currentIndexChanged(int)', self._filter)
        self._filterWheelGuard = self._wheelGuardClass(self.progressFilter)
        self.progressFilter.setFocusPolicy(qt.Qt.TabFocus)
        lay.addWidget(self.progressFilter)
        self.caseTable = qt.QTableWidget(0,2)
        palette = self.caseTable.palette
        for role in [qt.QPalette.Text,qt.QPalette.WindowText,qt.QPalette.ButtonText]:
            palette.setColor(role,qt.QColor('#263642'))
        palette.setColor(qt.QPalette.Base,qt.QColor('#edf0f2'))
        palette.setColor(qt.QPalette.Highlight,qt.QColor('#dfedf7'))
        palette.setColor(qt.QPalette.HighlightedText,qt.QColor('#203340'))
        self.caseTable.palette = palette
        self.caseTable.horizontalHeader().palette = palette
        self.caseTable.setHorizontalHeaderLabels(['Case', 'Whole status'])
        self.caseTable.verticalHeader().hide()
        self.caseTable.verticalHeader().setDefaultSectionSize(52)
        self.caseTable.horizontalHeader().setStretchLastSection(True)
        self.caseTable.horizontalHeader().minimumSectionSize = 60
        self.caseTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        self.caseTable.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
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
        # Dataset and reader provenance live with Case details, not in a banner.
        self.message = qt.QLabel('Open a dataset to begin.')
        self.message.objectName = 'support'
        self.message.wordWrap = True
        self.message.setMaximumHeight(72)
        lay.addWidget(self.message)
        self.caseListDock.setWidget(panel)
        self.caseListDock.setMinimumWidth(218)
        slicer.util.mainWindow().addDockWidget(qt.Qt.LeftDockWidgetArea,self.caseListDock)

    def _buildEditor(self):
        self.rightDock = qt.QDockWidget('Annotation',slicer.util.mainWindow())
        self.rightDock.objectName = 'MeniscusAnnotationTools'
        self.rightDock.setFeatures(qt.QDockWidget.NoDockWidgetFeatures)
        self.rightDock.setTitleBarWidget(qt.QWidget(self.rightDock))
        panel, lay = self._panel()
        self.annotationTitle = self._title('Annotation',lay)
        self.plausibilityButton = self._button('Inspect label positions',self._showPlausibility,lay)
        self.plausibilityButton.objectName = 'MeniscusPlausibilityAdvisory'
        self.plausibilityButton.setToolTip('Non-blocking physical-position advisory. No labels are changed.')
        self.plausibilityButton.hide()
        labels = qt.QHBoxLayout()
        self.labelButtons = {}
        for key in ['medial','lateral']:
            name,color = LABELS[key]
            b = self._button('Medial' if key=='medial' else 'Lateral',lambda k=key:self.setLabel(k),labels)
            b.setIcon(self._icon('dot',qt.QColor.fromRgbF(*color).name()))
            b.setCheckable(True)
            b.setToolTip(name)
            b.setAccessibleName(name)
            self.labelButtons[key] = b
        lay.addLayout(labels)
        self.taskSelector = self._choiceStrip([
            ('whole','Whole meniscus','Whole meniscus','MeniscusTaskWhole'),
            ('regions','Regions (draft)','Regions (draft)','MeniscusTaskRegions')],panel)
        self.taskCombo = self.taskSelector.model
        self.taskButtons = self.taskSelector.buttons
        self.taskCombo.setAccessibleName('Annotation task')
        self.taskCombo.connect('currentIndexChanged(int)',self._taskChanged)
        lay.addWidget(self.taskSelector)
        b = self._button('Uncertain area',lambda:self.setLabel('uncertain'),lay)
        b.setIcon(self._icon('dot',qt.QColor.fromRgbF(*LABELS['uncertain'][1]).name()))
        b.setCheckable(True)
        b.setAccessibleName('Uncertain area')
        self.labelButtons['uncertain'] = b
        self.regionPanel = qt.QWidget()
        regionLayout = qt.QVBoxLayout(self.regionPanel)
        regionLayout.setContentsMargins(0,0,0,0)
        regionLayout.setSpacing(6)
        self.regionSelector = self._choiceStrip([
            ('anterior','Anterior horn','AH','MeniscusRegionAnterior'),
            ('body','Body region','Body','MeniscusRegionBody'),
            ('posterior','Posterior horn','PH','MeniscusRegionPosterior')],self.regionPanel)
        self.regionCombo = self.regionSelector.model
        self.regionButtons = self.regionSelector.buttons
        self.regionCombo.setAccessibleName('Selected meniscal region')
        self.regionCombo.connect('currentIndexChanged(int)',self._regionChanged)
        regionLayout.addWidget(self.regionSelector)
        self.regionMeaning = qt.QLabel('AH anterior horn · Body · PH posterior horn')
        self.regionMeaning.objectName = 'support'
        self.regionMeaning.wordWrap = True
        self.regionMeaning.setToolTip('Body is a regional assignment inside the complete meniscus. Correct the whole mask in Whole meniscus first.')
        regionLayout.addWidget(self.regionMeaning)
        self.boundaryUncertainButton = self._button('Boundary uncertain',self._boundaryUncertain,regionLayout)
        self.boundaryUncertainButton.setCheckable(True)
        self.boundaryUncertainButton.setIcon(self._icon('dot',qt.QColor.fromRgbF(*LABELS['uncertain'][1]).name()))
        self.boundaryUncertainButton.setToolTip('Separate regional boundary uncertainty, restricted to the selected meniscus.')
        self.regionalProtocolLabel = qt.QLabel('Draft regions · Protocol pending')
        self.regionalProtocolLabel.objectName = 'support'
        self.regionalProtocolLabel.wordWrap = True
        self.regionalProtocolLabel.setToolTip('Regional boundaries require an expert-defined protocol. Regional research approval is unavailable.')
        regionLayout.addWidget(self.regionalProtocolLabel)
        lay.addWidget(self.regionPanel)
        self.regionPanel.hide()
        # Retained as an internal selection model for compatibility, not a hidden image layer.
        self.labelCombo = qt.QComboBox(panel)
        self.labelCombo.addItems([value[0] for value in LABELS.values()])
        self.labelCombo.hide()
        strip = qt.QWidget()
        strip.objectName = 'toolStrip'
        tools = qt.QHBoxLayout(strip)
        tools.setContentsMargins(2,2,2,2)
        tools.setSpacing(1)
        self.toolButtons = {}
        for name in ['Draw','Erase','Paint']:
            b = qt.QToolButton()
            b.setText(name)
            b.setIcon(self._icon(name.lower()))
            b.setIconSize(qt.QSize(16,16))
            b.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Fixed)
            b.objectName = 'drawingTool'
            b.setMinimumHeight(30)
            b.setCheckable(True)
            b.connect('clicked()',lambda n=name:self.setTool(n))
            tools.addWidget(b, 3 if name=='Draw' else 2)
            if name=='Draw':
                b.setProperty('preferredTool',True)
                b.setToolTip('Main boundary tool: click points, then right-click to close and fill.')
            self.toolButtons[name] = b
        lay.addWidget(strip)
        self.toolText = qt.QLabel('Choose a case to annotate')
        self.toolText.objectName = 'support'
        self.toolText.wordWrap = True
        self.toolText.setMinimumHeight(18)
        lay.addWidget(self.toolText)
        self.brushRow = qt.QWidget()
        brush = qt.QHBoxLayout(self.brushRow)
        brush.setContentsMargins(0,0,0,0)
        brush.addWidget(qt.QLabel('Brush size'))
        self.brushSize = qt.QDoubleSpinBox()
        self.brushSize.setRange(.3,30)
        self.brushSize.setSingleStep(.5)
        self.brushSize.setSuffix(' mm')
        self.brushSize.setDecimals(1)
        self.brushSize.setValue(float(self.settings.value('Meniscus/brush',3)))
        self.brushSize.connect('valueChanged(double)',self._brush)
        brush.addWidget(self.brushSize,1)
        lay.addWidget(self.brushRow)
        history = qt.QHBoxLayout()
        history.setSpacing(4)
        self.undoButton = self._button('Undo',self._undo,history,icon='undo')
        self.redoButton = self._button('Redo',self._redo,history,icon='redo')
        lay.addLayout(history)
        self.visible = qt.QCheckBox('Show annotation')
        self.visible.setChecked(True)
        self.visible.connect('toggled(bool)',self._display)
        lay.addWidget(self.visible)
        display = ctk.ctkCollapsibleButton()
        display.text = 'Image and annotation display'
        display.collapsed = True
        inner = qt.QVBoxLayout(display)
        inner.setContentsMargins(0,8,0,8)
        row = qt.QHBoxLayout()
        self.fill = qt.QCheckBox('Transparent fill')
        self.fill.setChecked(str(self.settings.value('Meniscus/fill','false')).lower()=='true')
        self.fill.connect('toggled(bool)',self._display)
        row.addWidget(self.fill)
        inner.addLayout(row)
        inner.addWidget(qt.QLabel('Fill opacity'))
        self.opacity = qt.QSlider(qt.Qt.Horizontal)
        self.opacity.setRange(0,100)
        self.opacity.setValue(int(self.settings.value('Meniscus/opacity',20)))
        self.opacity.connect('valueChanged(int)',self._display)
        inner.addWidget(self.opacity)
        thicknessRow = qt.QHBoxLayout()
        thicknessRow.addWidget(qt.QLabel('Outline width'))
        self.outlineWidth = qt.QSpinBox()
        self.outlineWidth.setRange(1,4)
        self.outlineWidth.setSuffix(' px')
        self.outlineWidth.setValue(int(self.settings.value('Meniscus/outlineWidth',2)))
        self.outlineWidth.connect('valueChanged(int)',self._display)
        thicknessRow.addWidget(self.outlineWidth)
        inner.addLayout(thicknessRow)
        self.regionLegend = qt.QLabel('')
        self.regionLegend.wordWrap = True
        self.regionLegend.setTextFormat(qt.Qt.RichText)
        inner.addWidget(self.regionLegend)
        self.windowLevelButton = self._button('Window/level',self._windowLevel,inner)
        self.windowLevelButton.setCheckable(True)
        self.windowLevelButton.setToolTip('Left-drag on the image to adjust brightness and contrast. Choose Paint, Draw or Erase to return to annotation.')
        self._button('Reset view',self._resetView,inner,icon='reset')
        self.reformats = qt.QCheckBox('Show orientation views')
        self.reformats.setToolTip('Coronal and axial reformats are for orientation. Editing stays on the acquired sagittal view.')
        self.reformats.connect('toggled(bool)',self._layoutViews)
        inner.addWidget(self.reformats)
        self.showRegions = qt.QCheckBox('Show regions')
        self.showRegions.setChecked(False)
        self.showRegions.connect('toggled(bool)',self._display)
        inner.addWidget(self.showRegions)
        lay.addWidget(display)
        self.regionalAssessmentPanel = ctk.ctkCollapsibleButton()
        self.regionalAssessmentPanel.text = 'Regional assessment'
        self.regionalAssessmentPanel.collapsed = True
        regionalLay = qt.QVBoxLayout(self.regionalAssessmentPanel)
        regionalLay.setContentsMargins(0,6,0,6)
        regionalLay.addWidget(qt.QLabel('Region assessment'))
        self.assessmentSelector = self._choiceStrip([
            ('unassessed','Not assessed','Not assessed','MeniscusAssessmentUnassessed'),
            ('present','Present','Present','MeniscusAssessmentPresent'),
            ('absent','Absent','Absent','MeniscusAssessmentAbsent'),
            ('uncertain','Uncertain','Uncertain','MeniscusAssessmentUncertain')],self.regionalAssessmentPanel,rows=2)
        self.regionStatusCombo = self.assessmentSelector.model
        self.assessmentButtons = self.assessmentSelector.buttons
        self.regionStatusCombo.setAccessibleName('Selected region assessment')
        self.regionStatusCombo.connect('currentIndexChanged(int)',self._regionalAssessmentChanged)
        regionalLay.addWidget(self.assessmentSelector)
        self.regionNotes = qt.QTextEdit()
        self.regionNotes.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Fixed)
        self.regionNotes.setFixedHeight(58)
        self.regionNotes.setPlaceholderText('Note for the selected region')
        self.regionNotes.connect('textChanged()',self._regionalNoteChanged)
        regionalLay.addWidget(self.regionNotes)
        self.regionalFlag = qt.QCheckBox('Flag regional review')
        self.regionalFlag.setToolTip('Flag regional review on this acquired slice; whole-meniscus review is unchanged.')
        self.regionalFlag.connect('toggled(bool)',self._regionalFlagChanged)
        regionalLay.addWidget(self.regionalFlag)
        self.regionalSummary = qt.QLabel('')
        self.regionalSummary.objectName = 'support'
        self.regionalSummary.wordWrap = True
        regionalLay.addWidget(self.regionalSummary)
        lay.addWidget(self.regionalAssessmentPanel)
        self.regionalAssessmentPanel.hide()
        self.notesPanel = ctk.ctkCollapsibleButton()
        self.notesPanel.text = 'Case notes and slice flag'
        self.notesPanel.collapsed = True
        notesLay = qt.QVBoxLayout(self.notesPanel)
        notesLay.setContentsMargins(0,6,0,6)
        self.attention = qt.QCheckBox('Flag this slice')
        self.attention.connect('toggled(bool)',self._flag)
        notesLay.addWidget(self.attention)
        self.notes = qt.QTextEdit()
        self.notes.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Fixed)
        self.notes.setPlaceholderText('Notes for this case or uncertain findings')
        self.notes.setFixedHeight(78)
        self.notes.connect('textChanged()',self._notesChanged)
        notesLay.addWidget(self.notes)
        lay.addWidget(self.notesPanel)
        review = ctk.ctkCollapsibleButton()
        review.text = 'Case details and approval'
        review.collapsed = True
        self.caseReviewPanel = review
        reviewLay = qt.QVBoxLayout(review)
        reviewLay.setContentsMargins(0,8,0,8)
        self.initializationLabel = qt.QLabel('')
        self.initializationLabel.wordWrap = True
        self.initializationLabel.objectName = 'support'
        reviewLay.addWidget(self.initializationLabel)
        reviewLay.addWidget(self.datasetLabel)
        self.medialConsidered = qt.QCheckBox('Medial considered')
        self.lateralConsidered = qt.QCheckBox('Lateral considered')
        self.medialConsidered.setToolTip('Confirm that you considered the medial meniscus throughout the acquired stack.')
        self.lateralConsidered.setToolTip('Confirm that you considered the lateral meniscus throughout the acquired stack.')
        for checkbox in [self.medialConsidered,self.lateralConsidered]:
            checkbox.connect('toggled(bool)',self._compartments)
            reviewLay.addWidget(checkbox)
        self.protocolLabel = qt.QLabel('Practice work · Draft protocol')
        self.protocolLabel.objectName = 'support'
        self.protocolLabel.wordWrap = True
        reviewLay.addWidget(self.protocolLabel)
        self.approvalStateLabel = qt.QLabel('')
        self.approvalStateLabel.objectName = 'support'
        self.approvalStateLabel.wordWrap = True
        reviewLay.addWidget(self.approvalStateLabel)
        self.approveButton = self._button('Approve case',self._approve,reviewLay,icon='check')
        self.approveButton.setToolTip('Approval is separate from saving and requires every acquired slice to be reviewed.')
        lay.addWidget(review)
        for section in panel.findChildren(ctk.ctkCollapsibleButton):
            policy = section.sizePolicy
            policy.setHorizontalPolicy(qt.QSizePolicy.Preferred)
            section.setSizePolicy(policy)
        lay.addStretch(1)
        self.editor = slicer.qMRMLSegmentEditorWidget(panel)
        self.editor.setMRMLScene(slicer.mrmlScene)
        self.editor.setMaximumNumberOfUndoStates(30)
        self.editor.setUndoEnabled(True)
        self.editor.setEffectNameOrder(['Draw','Erase','Paint'])
        self.editor.unorderedEffectsVisible = False
        self.editor.autoShowSourceVolumeNode = False
        for method in ['setSourceVolumeNodeSelectorVisible','setSegmentationNodeSelectorVisible','setSwitchToSegmentationsButtonVisible','setShow3DButtonVisible']:
            if hasattr(self.editor,method): getattr(self.editor,method)(False)
        self.editor.hide()
        scroll = qt.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(qt.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setStyleSheet(self.style)
        self.rightDock.setWidget(scroll)
        self.rightDock.setMinimumWidth(238)
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
        self.appTitle = qt.QLabel('Meniscus Annotator')
        self.appTitle.objectName = 'appTitle'
        self.topBar.addWidget(self.appTitle)
        self.casesToggle = self._headerButton('Cases','cases')
        self.casesToggle.setCheckable(True)
        self.casesToggle.setChecked(True)
        self.casesToggle.connect('toggled(bool)',lambda visible:self._setPanelVisible('cases',visible))
        self.caseListDock.connect('visibilityChanged(bool)',lambda visible:self._panelVisibilityChanged(self.casesToggle,visible))
        identity = qt.QWidget()
        identity.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Preferred)
        identityLayout = qt.QVBoxLayout(identity)
        identityLayout.setContentsMargins(0,0,0,0)
        identityLayout.setSpacing(0)
        self.identityLabel = qt.QLabel('Choose a dataset')
        self.identityLabel.objectName = 'identity'
        self.identityLabel.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Preferred)
        identityLayout.addWidget(self.identityLabel)
        self.contextLabel = qt.QLabel('Reader not confirmed · No dataset')
        self.contextLabel.objectName = 'support'
        self.contextLabel.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Preferred)
        identityLayout.addWidget(self.contextLabel)
        self.topBar.addWidget(identity)
        self.saveStatus = qt.QLabel('Not connected')
        self.saveStatus.objectName = 'saveState'
        self.saveStatus.setFixedWidth(max(170,qt.QFontMetrics(self.font).horizontalAdvance('Practice · Unsaved changes')+16))
        self.topBar.addWidget(self.saveStatus)
        self.datasetMenuButton = self._headerButton('Dataset','folder')
        self._menu(self.datasetMenuButton,[('Open dataset…',self._chooseDataset,'folder'),('Resume work',self._resume,'resume'),('Reader and dataset…',self._showContext,'help'),(None,None,None),('Show dataset folder',self._showDataset,'folder'),('Show saved work',self._showWork,'folder'),('Export results…',self._exportDialog,'export')])
        self.toolsToggle = self._headerButton('Tools','tools')
        self.toolsToggle.setCheckable(True)
        self.toolsToggle.setChecked(True)
        self.toolsToggle.connect('toggled(bool)',lambda visible:self._setPanelVisible('tools',visible))
        self.rightDock.connect('visibilityChanged(bool)',lambda visible:self._panelVisibilityChanged(self.toolsToggle,visible))
        helpButton = self._headerButton('Help','help')
        self._menu(helpButton,[('Controls and shortcuts',self._help,'help'),('Annotation setup…',self._loadJob,'folder'),('Troubleshooting',self._diagnostics,'help'),('About Meniscus Annotator',self._about,'help')])
        main.addToolBar(qt.Qt.TopToolBarArea,self.topBar)
        main.addToolBarBreak(qt.Qt.TopToolBarArea)
        self.stepBar = qt.QToolBar('Current annotation step',main)
        self.stepBar.objectName = 'MeniscusNextStep'
        self.stepBar.setMovable(False)
        self.stepBar.setStyleSheet(self.style)
        self.stepPanel = qt.QWidget()
        self.stepPanel.objectName = 'MeniscusStepPanel'
        self.stepPanel.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Preferred)
        stepLayout = qt.QHBoxLayout(self.stepPanel)
        stepLayout.setContentsMargins(8,2,8,2)
        stepLayout.setSpacing(8)
        self.instruction = qt.QLabel('Open a dataset, then confirm your reader identity.')
        self.instruction.objectName = 'MeniscusInstruction'
        self.instruction.wordWrap = True
        self.instruction.setSizePolicy(qt.QSizePolicy.Ignored,qt.QSizePolicy.Preferred)
        self.instruction.setMinimumWidth(100)
        stepLayout.addWidget(self.instruction,1)
        self.finishContourButton = qt.QPushButton('Finish contour')
        self.finishContourButton.objectName = 'primary'
        self.finishContourButton.setIcon(self._icon('check','#ffffff'))
        self.finishContourButton.connect('clicked()',self._finishContour)
        stepLayout.addWidget(self.finishContourButton)
        self.discardContourButton = qt.QPushButton('Discard')
        self.discardContourButton.connect('clicked()',self._discardContour)
        self.discardContourButton.setToolTip('Discard only the unfinished contour; committed annotations stay unchanged.')
        stepLayout.addWidget(self.discardContourButton)
        self.goApprovalButton = qt.QPushButton('Go to approval')
        self.goApprovalButton.objectName = 'MeniscusGoApproval'
        self.goApprovalButton.connect('clicked()',self._goApproval)
        stepLayout.addWidget(self.goApprovalButton)
        self.notificationUndoButton = qt.QPushButton('Undo transfer')
        self.notificationUndoButton.connect('clicked()',self._undo)
        stepLayout.addWidget(self.notificationUndoButton)
        for button in (self.finishContourButton,self.discardContourButton,self.goApprovalButton,self.notificationUndoButton):
            button.hide()
        self.stepBar.addWidget(self.stepPanel)
        main.addToolBar(qt.Qt.TopToolBarArea,self.stepBar)
        self.bottomBar = qt.QToolBar('Acquired slices and review',main)
        self.bottomBar.objectName = 'MeniscusNavigation'
        self.bottomBar.setMovable(False)
        self.bottomBar.setFont(self.font)
        self.bottomBar.setStyleSheet(self.style)
        footer = qt.QWidget()
        self.navigationPanel = footer
        footer.objectName = 'navigationPanel'
        footer.setSizePolicy(qt.QSizePolicy.Expanding,qt.QSizePolicy.Preferred)
        nav = qt.QHBoxLayout(footer)
        nav.setContentsMargins(2,2,2,2)
        nav.setSpacing(6)
        self.actionBar = footer
        self.sliceReadout = qt.QLabel('Slice — of —')
        self.sliceReadout.objectName = 'sliceReadout'
        self.sliceReadout.setMinimumWidth(104)
        nav.addWidget(self.sliceReadout)
        self.previousButton = self._button('',lambda:self.goSlice(self.currentSlice-1),nav,icon='previous')
        self.previousButton.setAccessibleName('Previous acquired slice')
        self.previousButton.setToolTip('Previous acquired slice · Left arrow')
        self.previousButton.setFixedWidth(30)
        self.sliceSlider = qt.QSlider(qt.Qt.Horizontal)
        self.sliceSlider.setRange(1,1)
        self.sliceSlider.setSingleStep(1)
        self.sliceSlider.setPageStep(1)
        self.sliceSlider.setMinimumWidth(60)
        self.sliceSlider.setToolTip('Every acquired slice in source order. Displayed slice 1 is stored index 0.')
        self.sliceSlider.setAccessibleName('Acquired slice')
        self.sliceSlider.connect('valueChanged(int)',lambda value:self.goSlice(value-1))
        nav.addWidget(self.sliceSlider,1)
        self.nextButton = self._button('',lambda:self.goSlice(self.currentSlice+1),nav,icon='next')
        self.nextButton.setAccessibleName('Next acquired slice')
        self.nextButton.setToolTip('Next acquired slice · Right arrow')
        self.nextButton.setFixedWidth(30)
        self.goToLabel = qt.QLabel('Go to')
        nav.addWidget(self.goToLabel)
        self.sliceSpin = qt.QSpinBox()
        self.sliceSpin.setRange(1,1)
        self.sliceSpin.setFixedWidth(60)
        self.sliceSpin.setAccessibleName('Go to acquired slice')
        self.sliceSpin.connect('valueChanged(int)',lambda value:self.goSlice(value-1))
        nav.addWidget(self.sliceSpin)
        self.progress = qt.QLabel('No slices reviewed')
        self.progress.objectName = 'support'
        nav.addWidget(self.progress)
        self.sliceState = qt.QLabel('No case')
        self.sliceState.objectName = 'support'
        nav.addWidget(self.sliceState)
        self.jumpButton = qt.QToolButton()
        self.jumpButton.setText('Jump')
        self.jumpButton.objectName = 'quiet'
        self.jumpButton.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        self.jumpButton.setIcon(self._icon('next'))
        self._menu(self.jumpButton,[('Next unreviewed slice',self._nextUnreviewed,'next'),('Next flagged slice',self._nextFlagged,'flag')])
        nav.addWidget(self.jumpButton)
        self.reviewButton = self._button('Mark reviewed and next',self._reviewNext,nav,True,icon='check')
        self.saveButton = self._button('Save draft',lambda:self._safe(self.save),nav,icon='save')
        self.saveButton.objectName = 'saveDraft'
        self.bottomBar.addWidget(footer)
        main.addToolBar(qt.Qt.BottomToolBarArea,self.bottomBar)

    def _setPanelVisible(self, name, visible):
        dock = self.caseListDock if name == 'cases' else self.rightDock
        dock.setVisible(visible)
        self.settings.setValue('Meniscus/' + name + 'Visible',bool(visible))
        self.settings.sync()

    @staticmethod
    def _syncPanelToggle(button, visible):
        button.blockSignals(True)
        button.setChecked(visible)
        button.blockSignals(False)

    def _panelVisibilityChanged(self, button, visible):
        self._syncPanelToggle(button,visible)
        self._updateGuidance()

    def _adaptWorkspace(self):
        if not hasattr(self,'goToLabel'):
            return
        width = slicer.util.mainWindow().width
        self.appTitle.setVisible(width >= 1180)
        self.goToLabel.setVisible(width >= 1100)
        self.sliceSpin.setVisible(width >= 940)
        self.sliceState.setVisible(width >= 1180)
        self.jumpButton.setVisible(width >= 900)
        # The current slice, review and save controls remain visible. Secondary
        # text is available through tooltips when the work area is narrow.
        self.progress.setVisible(width >= 1380)
        self.progress.setToolTip(str(self.progress.text))
        self.jumpButton.setToolTip(str(self.progress.text) + ' · Jump to an unreviewed or flagged slice')
        self._refreshHeaderContext()
        self._queueNavigationFit()

    def _queueNavigationFit(self):
        if not hasattr(self,'navigationPanel') or getattr(self,'_navigationFitQueued',False):
            return
        self._navigationFitQueued = True
        qt.QTimer.singleShot(0,self._fitNavigation)

    def _fitNavigation(self):
        self._navigationFitQueued = False
        if hasattr(self,'stepPanel'):
            step_height = max(34,self.stepPanel.layout().heightForWidth(self.stepPanel.width))
            if self.stepPanel.minimumHeight!=step_height or self.stepPanel.maximumHeight!=step_height:
                self.stepPanel.setFixedHeight(step_height)
                self.stepPanel.updateGeometry()
        panel = self.navigationPanel
        # QToolBar otherwise uses the wrapped label's narrow preferred width
        # to choose height, leaving a large blank row at the actual window width.
        desired = max(36,panel.layout().heightForWidth(panel.width))
        if panel.minimumHeight != desired or panel.maximumHeight != desired:
            panel.setFixedHeight(desired)
            panel.updateGeometry()

    def _finishLayout(self):
        main = slicer.util.mainWindow()
        for bar in main.findChildren(qt.QToolBar):
            if bar not in [self.topBar,self.stepBar,self.bottomBar]: bar.hide()
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
        main.setMinimumSize(800,480)
        main.setStyleSheet('QMainWindow { background:#101820; } QMainWindow::separator { background:#bdc8d0; width:1px; height:1px; }')
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        for action in main.findChildren(qt.QAction):
            if not any(word in str(action.objectName) for word in ['Exit','Quit']): action.setShortcut(qt.QKeySequence())
        self._installShortcuts()
        main.resizeDocks([self.caseListDock,self.rightDock],[int(self.settings.value('Meniscus/casesWidth',224)),int(self.settings.value('Meniscus/toolsWidth',244))],qt.Qt.Horizontal)
        for name,dock,button in [('cases',self.caseListDock,self.casesToggle),('tools',self.rightDock,self.toolsToggle)]:
            visible = str(self.settings.value('Meniscus/' + name + 'Visible','true')).lower() not in ('false','0')
            dock.setVisible(visible)
            self._syncPanelToggle(button,visible)
        self.layoutObserver = WorkspaceLayoutObserver(self)
        main.installEventFilter(self.layoutObserver)
        self._adaptWorkspace()
        self._lockControllers()
        from MeniscusAnnotatorLib.interface import EmptyCanvas
        self.emptyCanvas = EmptyCanvas(slicer.app.layoutManager().sliceWidget('Red').sliceView(),self)
        self.emptyCanvas.ready(bool(self.dataset))

    def _updatePracticeContext(self):
        context = (self.session.state.get('practice_context') if self.session else None) or (getattr(self.store,'practice_context',None) if self.store else None)
        if context:
            automated = context.get('actor_type')=='automated'
            slicer.util.mainWindow().setWindowTitle('Meniscus Annotator ' + VERSION + (' — AUTOMATED SOFTWARE QA' if automated else ' — SOFTWARE PRACTICE — not research annotations'))
            self.protocolLabel.setText('Automated software practice · Not human annotations' if automated else 'Software practice · Not accepted research annotations')
        return context

    def _showDataset(self):
        if self.dataset: qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(self.dataset.root)))

    def _diagnostics(self):
        details = {'application_version':VERSION,'source_identity':SOURCE_IDENTITY,'slicer_version':slicer.app.applicationVersion,'slicer_revision':slicer.app.repositoryRevision,'qt_version':qt.qVersion(),'platform':sys.platform,'scale_rounding_environment':os.environ.get('QT_SCALE_FACTOR_ROUNDING_POLICY')}
        slicer.util.infoDisplay(json.dumps(details,indent=2) + '\n\n' + (self._diagnostic or 'No errors recorded in this session.'),windowTitle='Troubleshooting — keep details private')

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
        main = slicer.util.mainWindow()
        for key, cb in [('Left', lambda:self.goSlice(self.currentSlice-1)),('Right', lambda:self.goSlice(self.currentSlice+1)),('R',self._reviewNext),('U',self._nextUnreviewed),('F',self._nextFlagged),('Ctrl+S',lambda:self._safe(self.save)),('Ctrl+Z',self._undo),('Ctrl+Y',self._redo),('1',lambda:self.setLabel('medial')),('2',lambda:self.setLabel('lateral')),('3',lambda:self.setLabel('uncertain')),('P',lambda:self.setTool('Paint')),('D',lambda:self.setTool('Draw')),('E',lambda:self.setTool('Erase')),('Escape',self._escape)]:
            shortcut = qt.QShortcut(qt.QKeySequence(key),main)
            shortcut.setContext(qt.Qt.WindowShortcut)
            shortcut.connect('activated()',lambda callback=cb:self._runShortcut(callback))
            self.shortcuts.append(shortcut)
        slicer.app.connect('focusChanged(QWidget*,QWidget*)',self._shortcutFocusChanged)
        self._shortcutFocusChanged(None,qt.QApplication.focusWidget())

    @staticmethod
    def _textInputFocused(widget=None):
        current = widget if widget is not None else qt.QApplication.focusWidget()
        while current:
            if isinstance(current,(qt.QLineEdit,qt.QTextEdit,qt.QPlainTextEdit,qt.QAbstractSpinBox,qt.QComboBox)):
                return True
            current = current.parentWidget()
        return False

    def _shortcutFocusChanged(self, previous, current):
        enabled = not self._textInputFocused(current)
        for shortcut in self.shortcuts:
            shortcut.setEnabled(enabled)

    def _runShortcut(self, callback):
        if self.session and not self._textInputFocused() and qt.QApplication.activeModalWidget() is None:
            callback()

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
            if getattr(func,'__name__','') == 'save':
                self.saveStatus.setText('Save failed')
                self.saveStatus.setToolTip('Unsaved changes. Check the work location, available disk space and permissions, then retry Save draft.')
            advice = ('\n\nContact the dataset coordinator if the input or saved-work configuration needs correction. Diagnostic details are available in Help.'
                      if isinstance(exc, ValidationError) else
                      '\n\nCheck the work location, available disk space and permissions, then retry. Diagnostic details are available in Help.')
            slicer.util.errorDisplay(reason + advice, windowTitle='Meniscus annotation')
            return None

    def _chooseReaderIdentity(self, previous=''):
        dialog = qt.QDialog(slicer.util.mainWindow())
        dialog.objectName = 'MeniscusReaderIdentityDialog'
        dialog.setWindowTitle('Confirm reader identity')
        dialog.setStyleSheet(self.style)
        layout = qt.QVBoxLayout(dialog)
        explanation = qt.QLabel('Use your own name or study ID. Each reader has separate saved work. Confirm your identity whenever you reopen an assignment on a shared computer.')
        explanation.wordWrap = True
        layout.addWidget(explanation)
        if previous:
            last = qt.QLabel('Last used: ' + previous)
            last.wordWrap = True
            layout.addWidget(last)
        layout.addWidget(qt.QLabel('Reader name or study ID'))
        entry = qt.QLineEdit()
        entry.objectName = 'MeniscusReaderIdentityInput'
        entry.setPlaceholderText('Enter your name or assigned reader ID')
        entry.setText(previous)
        layout.addWidget(entry)
        confirmation = qt.QCheckBox('I confirm this is my reader identity')
        confirmation.objectName = 'MeniscusReaderIdentityConfirmed'
        layout.addWidget(confirmation)
        buttons = qt.QDialogButtonBox()
        proceed = buttons.addButton('Continue',qt.QDialogButtonBox.AcceptRole)
        proceed.objectName = 'MeniscusReaderIdentityContinue'
        buttons.addButton('Cancel',qt.QDialogButtonBox.RejectRole)
        proceed.setEnabled(False)
        def ready(*args):
            proceed.setEnabled(bool(str(entry.text).strip()) and confirmation.checked)
        entry.connect('textChanged(QString)',lambda text:(confirmation.setChecked(False),ready()))
        confirmation.connect('toggled(bool)',ready)
        buttons.connect('accepted()',dialog.accept)
        buttons.connect('rejected()',dialog.reject)
        layout.addWidget(buttons)
        entry.setFocus()
        entry.selectAll()
        if dialog.exec_()!=qt.QDialog.Accepted:
            return None
        reader = str(entry.text).strip()
        return reader if reader and confirmation.checked else None

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
        if self.session and not self._guardContour('opening another dataset'):
            return
        root = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), 'Open dataset', str(self.settings.value('Meniscus/dataset', '')))
        if root:
            self._safe(lambda: self.openDataset(root))

    def openDataset(self, root, work_root=None):
        if getattr(self,'session',None) and not self._guardContour('opening another dataset'):
            return
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
        local_data = qt.QStandardPaths.writableLocation(qt.QStandardPaths.GenericDataLocation)
        local_default = Path(local_data) / 'MeniscusAnnotator' / 'work'
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
        location = work_root or (self._practiceConfig['work_root'] if self._practiceConfig else remembered) or str(local_default / workspace['relative_folder'])
        if self._practiceConfig and Path(location).resolve()!=Path(self._practiceConfig['work_root']).resolve():
            raise ValidationError('Software practice must use its separate local practice work folder.')
        if not work_root and not remembered and not self._practiceConfig:
            dialog = qt.QMessageBox(slicer.util.mainWindow())
            dialog.objectName = 'MeniscusWorkFolderDialog'
            dialog.setWindowTitle('Local work folder')
            dialog.setText('Keep active annotations in a local folder on this computer.')
            dialog.setInformativeText(str(location))
            dialog.setDetailedText('The suggested per-user folder is separate from the source dataset and return ZIPs. Known sync-managed locations are rejected; automatic detection is not comprehensive.')
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
        while True:
            problem = work_location_problem(location,ds.root)
            if not problem:
                try:
                    Path(location).mkdir(parents=True,exist_ok=True)
                    import uuid
                    probe = Path(location) / ('.meniscus-write-check-' + uuid.uuid4().hex)
                    try:
                        with probe.open('xb') as stream:
                            stream.write(b'local work write check')
                            stream.flush()
                            os.fsync(stream.fileno())
                    finally:
                        if probe.exists(): probe.unlink()
                except OSError:
                    problem = 'This folder is not writable. Choose a local folder you can write to, or ask your administrator to restore access to your existing saved work.'
            if not problem:
                break
            if work_root or self._practiceConfig:
                raise ValidationError(problem)
            warning = qt.QMessageBox(slicer.util.mainWindow())
            warning.objectName = 'MeniscusWorkFolderProblem'
            warning.setWindowTitle('Choose a local work folder')
            warning.setText(problem)
            warning.setInformativeText('Existing saved work has not been moved or changed. Choose another local folder, or cancel and restore access to the existing folder. Known sync providers are detected where possible, not comprehensively.')
            choose = warning.addButton('Choose another folder',qt.QMessageBox.AcceptRole)
            warning.addButton(qt.QMessageBox.Cancel)
            warning.exec_()
            if warning.clickedButton()!=choose:
                return None
            chosen = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(),'Choose local work folder',str(local_default))
            if not chosen:
                return None
            location = str(Path(chosen) if (Path(chosen)/'dataset.json').is_file() else Path(chosen)/workspace['relative_folder'])
        store = WorkStore(location, ds, job=job, reader=reader)
        if self.closeCase() is False:
            return
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
        self._updateGuidance()
        return ds

    def _loadJob(self):
        if self.session and not self._guardContour('changing annotation setup'):
            return
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
            if self.closeCase() is False:
                return
            self.store = WorkStore(self.store.root, self.dataset, job=job, reader=self._confirmedReader)
            self.settings.setValue('Meniscus/job/' + self.dataset.identity, str(path))
            self.message.setText('Explicit job loaded. Open a case; only permitted starting masks will be loaded.')
        self._safe(load)

    def _populate(self):
        if not self.dataset:
            return
        self.caseTable.setRowCount(len(self.dataset.cases))
        for row,case in enumerate(self.dataset.cases):
            m = case.metadata
            item = qt.QTableWidgetItem(f"{m['participant_id']}\nM{int(m['visit_month']):03d} · {'Left' if m['knee_side']=='L' else 'Right'}")
            item.setData(qt.Qt.UserRole,case.key)
            self.caseTable.setItem(row,0,item)
            status = 'Not started'
            rule = (self.store.job or {}).get('cases',{}).get(case.key,{})
            if rule.get('availability')=='unresolved':
                status = 'Blocked'
                item.setToolTip(str(rule.get('reason','Starting mask unresolved')))
            elif self.session and self.session.case.key==case.key:
                status = status_label(self.session.state,uncertainty=self._lastArrays[1])
            else:
                summary = self.store.summary(case)
                status = summary.get('display_status') or {'approved':'Research approved','practice_approved':'Practice approved','not_started':'Not started','needs_review':'Needs review','in_progress':'In progress','saved_unavailable':'Saved work needs attention','configuration_mismatch':'Saved work needs attention'}.get(summary.get('status'),'In progress')
                if summary.get('reason'):
                    item.setToolTip(summary['reason'])
            self.caseTable.setItem(row,1,qt.QTableWidgetItem(status))
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
            return True
        if not self._loading and not self._guardContour('closing or changing cases'):
            return False
        if not self._loading:
            self._segmentChanged()  # Commit a queued native stroke before switching/closing.
        if self.dirty or getattr(self.session,'review_journal_pending',False):
            self.save()
        self._loading = True
        self._removeDrawMarkers()
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
        self._drawContext = self._drawState = None
        self._startingMaskSlices = None
        self.regionalState = None
        self._lastRegionalArrays = None
        self.annotationTask = 'whole'
        self._regionBoundary = False
        self.taskCombo.blockSignals(True)
        self.taskCombo.setCurrentIndex(0)
        self.taskCombo.blockSignals(False)
        self.taskSelector.sync()
        self.regionPanel.hide()
        self.regionalAssessmentPanel.hide()
        self.labelButtons['uncertain'].show()
        self.notesPanel.show()
        self._drawHint = ''
        self._workflowHint = ''
        self._transferNotice = ''
        self._plausibility = None
        self._saveError = False
        self.plausibilityButton.hide()
        self._loading = False
        self._enable(False)
        self.sliceReadout.setText('Slice — of —')
        self.sliceState.setText('No case open')
        self.identityLabel.setText('Choose a case')
        self.annotationTitle.setText('Annotation')
        self.initializationLabel.setText('')
        self.saveStatus.setText('No work open')
        self._updateGuidance()
        if getattr(self,'emptyCanvas',None): self.emptyCanvas.ready(bool(self.dataset))
        return True

    def openCase(self, key):
        if self.session and self.session.case.key == key:
            return
        from MeniscusAnnotatorLib.core import require_case_prediction_available
        require_case_prediction_available(self.store.job, key)
        if self.closeCase() is False:
            return
        case = next(c for c in self.dataset.cases if c.key == key)
        self.session = self.store.open_case(case)
        if getattr(self,'emptyCanvas',None): self.emptyCanvas.hide()
        self._loading = True
        try:
            labels, uncertain, seg_path = self.session.load()
            regions, regional_uncertain, self.regionalState = self.session.load_regions()
            self._startingMaskSlices = None
            self._plausibility = label_plausibility(labels,case.affine_ras,case.metadata['knee_side'])
            if self.session.state['initialization']['method'] == 'correction':
                import nibabel as nib
                start = self.session.state['initialization']['starting_mask']
                preserved = self.session.folder / ('starting-mask-' + start['sha256'] + '.nii.gz')
                initial = np.asarray(nib.load(str(preserved)).dataobj)
                self._startingMaskSlices = np.any(initial != 0, axis=(0,1))
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
            self.anatomy = self._newSegmentation('Meniscus annotation', list(LABELS) + list(REGIONAL_LABELS))
            self.uncertainty = self.anatomy  # Separate binary segment, allowed to overlap anatomy.
            for segid, value in [('medial',1), ('lateral',2)]:
                slicer.util.updateSegmentBinaryLabelmapFromArray((labels==value).astype(np.uint8), self.anatomy, segid, self.volume)
            slicer.util.updateSegmentBinaryLabelmapFromArray(uncertain.astype(np.uint8), self.uncertainty, 'uncertain', self.volume)
            for region in REGIONS:
                slicer.util.updateSegmentBinaryLabelmapFromArray((regions == region['value']).astype(np.uint8),self.anatomy,region['id'],self.volume)
            slicer.util.updateSegmentBinaryLabelmapFromArray(regional_uncertain.astype(np.uint8),self.anatomy,'regional_uncertain',self.volume)
            self.editorNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentEditorNode')
            self.editorNode.SetSaveWithScene(False)
            self.editor.setMRMLSegmentEditorNode(self.editorNode)
            self.editorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
            self.editor.setSegmentationNode(self.anatomy)
            self.editor.setSourceVolumeNode(self.volume)
            self.editor.setCurrentSegmentID('medial')
            self.editor.setActiveEffectByName('Draw')
            self._configureEffects()
            self._lastArrays = self.collectArrays()
            self._lastRegionalArrays = self.collectRegionalArrays()
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
            if self.settings.contains(resume_key):
                self.currentSlice = int(self.settings.value(resume_key,0))
            elif self.session.current_checkpoint:
                self.currentSlice = int(self.session.state.get('last_slice',0))
            else:
                per_slice = np.count_nonzero(labels,axis=(1,2))
                self.currentSlice = int(per_slice.argmax()) if per_slice.any() else 0
            self._nativePlane(self.currentSlice, reset=True)
            sliceNode = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode()
            self._observers.append((sliceNode, sliceNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self._sliceMoved, 2.0)))
            self._installDrawGuards()
            self.sliceSpin.setMaximum(case.n_slices)
            self.sliceSlider.setMaximum(case.n_slices)
            self.notes.setPlainText(self.session.state.get('notes', ''))
            self.medialConsidered.setChecked(self.session.state['compartments']['medial'])
            self.lateralConsidered.setChecked(self.session.state['compartments']['lateral'])
            self.protocolLabel.setText('Practice work · Draft protocol' if self.session.state['protocol']['status']=='draft' else 'Protocol ' + self.session.state['protocol']['version'])
            self.dirty = False
            self._enable(True)
            self.setLabel('medial')
            self.setTool('Draw')
            prefix = 'Meniscus/target/' + self.session.case.identity + '/'
            compartment = str(self.settings.value(prefix + 'compartment','medial'))
            region = str(self.settings.value(prefix + 'region','anterior'))
            task = str(self.settings.value(prefix + 'task','whole'))
            self.setLabel(compartment if compartment in ('medial','lateral') else 'medial')
            self.setRegion(region if region in ('anterior','body','posterior') else 'anterior')
            self.setAnnotationTask(task if task in ('whole','regions') else 'whole')
            self.settings.setValue(getattr(self, '_lastCaseSettingsKey', 'Meniscus/lastCase'), key)
        except Exception:
            self.dirty = False
            self._loading = True  # Release a partial load without trying to serialize missing nodes.
            self.closeCase()
            raise
        self._loading = False
        self.refreshReview()
        self._populate()
        self.message.setText(self._plausibility.get('message','') if self._plausibility and self._plausibility.get('status')=='check' else '')
        if self.session.recovered:
            self.message.setText('Recovered the most recent intact checkpoint. A newer checkpoint was damaged; preserve the work folder for diagnostics.')
        if self.session.journal_warning:
            self.message.setText(self.session.journal_warning)
            self._workflowHint = self.session.journal_warning
            self._updateGuidance()
        return self.session

    def _newSegmentation(self, name, ids):
        node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', name)
        node.SetSaveWithScene(False)
        node.CreateDefaultDisplayNodes()
        node.GetDisplayNode().SetSaveWithScene(False)
        node.GetDisplayNode().SetSliceIntersectionThickness(int(self.outlineWidth.value))
        node.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
        for key in ids:
            name, color = (LABELS if key in LABELS else REGIONAL_LABELS)[key]
            node.GetSegmentation().AddEmptySegment(key, name, color)
        return node

    def _pendingDraw(self):
        """Inspect the pinned native Draw effect; never rasterize our own contour."""
        if not self.session or not hasattr(self,'editor'):
            return None
        effect = self.editor.effectByName('Draw')
        native = effect.self() if effect else None
        widget = slicer.app.layoutManager().sliceWidget('Red')
        pipeline = native.drawPipelines.get(widget) if native else None
        return pipeline if pipeline and pipeline.rasPoints.GetNumberOfPoints() else None

    def _guardContour(self, action):
        if not self._pendingDraw():
            return True
        self._workflowHint = ''
        self._drawHint = 'Finish or discard the contour before ' + action + '.'
        self._updateGuidance()
        return False

    def _resolveContourForClose(self):
        if not self._pendingDraw():
            return True
        if self._closingContourDialog:
            return False
        self._closingContourDialog = True
        try:
            pipeline = self._pendingDraw()
            dialog = qt.QMessageBox(slicer.util.mainWindow())
            dialog.objectName = 'MeniscusContourGuardDialog'
            dialog.setWindowTitle('Finish or discard the unfinished contour')
            dialog.setText(str(self.annotationTitle.text) + ' has an unfinished contour. The application is still responding.')
            dialog.setInformativeText('Finish it on this acquired slice, discard only these unfinished points, or keep drawing. Previous saved work is unchanged.')
            finish = dialog.addButton('Finish contour',qt.QMessageBox.AcceptRole)
            finish.setEnabled(pipeline.rasPoints.GetNumberOfPoints()>=3)
            discard = dialog.addButton('Discard contour',qt.QMessageBox.DestructiveRole)
            keep = dialog.addButton('Keep drawing',qt.QMessageBox.RejectRole)
            dialog.setDefaultButton(keep)
            dialog.setEscapeButton(keep)
            dialog.exec_()
            if dialog.clickedButton()==finish:
                self._finishContour()
            elif dialog.clickedButton()==discard:
                pipeline.resetPolyData()
                pipeline.actionState = ''
                pipeline.positionActors()
                self._drawContext = None
                self._drawHint = ''
                self._pollDrawState()
            else:
                self._guardContour('closing the application')
                return False
            return not bool(self._pendingDraw())
        finally:
            self._closingContourDialog = False

    def _refreshIdentity(self):
        if self.session:
            m = self.session.case.metadata
            side = 'Left knee' if m['knee_side']=='L' else 'Right knee'
            self.identityLabel.setText(f"OAI {m['participant_id']} · M{int(m['visit_month']):03d} · {side}")
            if self.annotationTask=='regions':
                suffix = 'Boundary uncertain' if self._regionBoundary else {'anterior':'Anterior horn','body':'Body','posterior':'Posterior horn'}[self.activeRegion]
                target = self._parentCompartment().capitalize() + ' · ' + suffix
            else:
                target = LABELS[self.activeLabel][0]
            self.identityLabel.setToolTip(target + ' · ' + side)
            self.annotationTitle.setText(target)
        self._refreshHeaderContext()

    def _refreshHeaderContext(self):
        if not hasattr(self,'contextLabel'):
            return
        if not self.store or not self.dataset:
            text = 'Reader not confirmed · No dataset'
        else:
            text = 'Reader: ' + self.store.annotator + ' · Dataset: ' + str(self.dataset.version)
        self.contextLabel.setToolTip(text)
        self.contextLabel.setAccessibleName(text)
        width = max(170,self.contextLabel.width)
        self.contextLabel.setText(qt.QFontMetrics(self.contextLabel.font).elidedText(text,qt.Qt.ElideMiddle,width))

    def _showContext(self):
        if not self.store:
            slicer.util.infoDisplay('No dataset is connected. Choose Open dataset, then confirm your reader identity.',windowTitle='Reader and dataset')
            return
        slicer.util.infoDisplay('Reader: ' + self.store.annotator + '\nDataset: ' + self.dataset.version + '\n\nActive work: ' + str(self.store.root) + '\nSource scans: ' + str(self.dataset.root) + '\n\nSource files are read only. Saved work and return ZIPs are separate.',windowTitle='Reader and dataset')

    def _isPractice(self):
        state = self.session.state if self.session else None
        protocol = (state or {}).get('protocol') or ((self.store.job or {}).get('protocol',{}) if self.store else {})
        return bool((state or {}).get('practice_context') or protocol.get('status')=='draft')

    def _goApproval(self):
        if not self.session or not self._guardContour('opening the approval checklist'):
            return
        if self.annotationTask!='whole':
            self.setAnnotationTask('whole')
        self.caseReviewPanel.collapsed = False
        slicer.app.processEvents()
        scroll = self.rightDock.findChild(qt.QScrollArea)
        if scroll:
            scroll.ensureWidgetVisible(self.approveButton)
        self.medialConsidered.setFocus()
        self._updateGuidance()

    def _updateGuidance(self):
        if not hasattr(self,'instruction'):
            return
        pending = self._pendingDraw()
        count = pending.rasPoints.GetNumberOfPoints() if pending else 0
        self.finishContourButton.setVisible(bool(count))
        self.discardContourButton.setVisible(bool(count))
        self.finishContourButton.setEnabled(count>=3)
        self.reviewButton.setEnabled(bool(self.session) and not count)
        self.saveButton.setEnabled(bool(self.session) and not count)
        self.undoButton.setEnabled(bool(self.session) and not count)
        self.redoButton.setEnabled(bool(self.session) and not count)
        self.goApprovalButton.hide()
        self.notificationUndoButton.setVisible(bool(self._transferNotice) and not count)
        if not self.session:
            self.instruction.setText('Choose a case to begin.' if self.dataset else 'Open a dataset, then confirm your reader identity.')
            self.brushRow.hide()
            return
        tool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Navigate'
        target = str(self.annotationTitle.text)
        whole = self.session.state
        all_reviewed = all(row['reviewed'] for row in whole['review'])
        approved = whole.get('status') in ('approved','practice_approved')
        if count:
            text = target + ' · Unfinished contour · ' + str(count) + ' points. ' + (self._drawHint or 'Right-click or Finish contour to close and fill.')
            self.saveStatus.setText(('Practice · ' if self._isPractice() else '') + 'Unsaved contour')
        elif self._transferNotice:
            text = self._transferNotice
        elif self.annotationTask=='whole' and approved:
            text = status_label(whole) + '. Continue inspection, or use Dataset → Export results.'
        elif self.annotationTask=='whole' and all_reviewed:
            text = 'All slices reviewed. Confirm both compartments and resolve uncertainty, then approve the case.'
            self.goApprovalButton.show()
            self.goApprovalButton.setProperty('primaryStep',True)
        elif self._workflowHint:
            text = self._workflowHint
        elif self._windowLevelActive:
            text = 'Left-drag to adjust brightness and contrast. Choose a drawing tool to return.'
        elif tool=='Draw':
            text = target + ' · Click around the boundary. Right-click to close and fill.'
        elif tool=='Erase':
            text = target + ' · Drag to remove pixels from the selected label.'
        elif tool=='Paint':
            text = target + ' · Drag to add pixels to the selected label.'
        else:
            text = 'Inspect this slice, then mark it reviewed. Scroll for slices; Ctrl+wheel zooms.'
        if not count and self.annotationTask=='regions':
            text += ' Draft regions stay inside the whole mask; use Whole meniscus to add tissue.'
        elif not count and not all_reviewed and (self._startingMaskSlices is None or not self._startingMaskSlices[self.currentSlice]):
            text += ' No starting mask on this slice; inspect the MRI.'
        self.instruction.setText(text)
        self.reviewButton.objectName = 'primary' if not count and not all_reviewed and not approved else 'quiet'
        self.reviewButton.setIcon(self._icon('check','#ffffff' if self.reviewButton.objectName=='primary' else '#425363'))
        self.reviewButton.setToolTip('Finish or discard the contour first.' if count else 'Explicit review of this acquired slice. Repeating an existing review does not remove approval.')
        self.saveButton.setToolTip('Finish or discard the contour before saving.' if count else 'Save a complete verified checkpoint; saving does not approve the case.')
        self.reviewButton.style().unpolish(self.reviewButton)
        self.reviewButton.style().polish(self.reviewButton)
        self._queueNavigationFit()

    def _validDrawContext(self, pipeline):
        if self._drawContext != self._drawingTargetContext():
            self._drawHint = 'The target changed. Discard this contour and return to the correct case and slice.'
            return False
        try:
            self._assertGrid()
        except ValidationError:
            self._diagnostic = traceback.format_exc()
            self._drawHint = 'Image alignment changed. Discard this contour and use Help → Controls and shortcuts → Restore last saved case before drawing.'
            qt.QTimer.singleShot(0,lambda message=self._drawHint: slicer.util.errorDisplay(message,windowTitle='Editing blocked'))
            return False
        points = np.asarray([pipeline.rasPoints.GetPoint(i) for i in range(pipeline.rasPoints.GetNumberOfPoints())])
        if len(points) < 3:
            self._drawHint = 'Add at least three boundary points, or discard the contour.'
            return False
        ijk = (np.linalg.inv(self.session.case.affine_ras) @ np.column_stack((points,np.ones(len(points)))).T).T[:,:3]
        if not np.allclose(ijk[:,2],self.currentSlice,atol=.001,rtol=0):
            self._drawHint = 'The contour is not on this acquired slice. Discard it and reopen the correct slice.'
            return False
        area = abs(np.dot(ijk[:,0],np.roll(ijk[:,1],1))-np.dot(ijk[:,1],np.roll(ijk[:,0],1))) / 2
        if area < 1e-8:
            self._drawHint = 'Place boundary points around an area before closing the contour.'
            return False
        return True

    def _finishContour(self):
        pipeline = self._pendingDraw()
        if not pipeline:
            return
        if not self._validDrawContext(pipeline):
            self._updateGuidance()
            return
        pipeline.apply()  # Native Slicer Draw, including its undo transaction.
        pipeline.actionState = ''
        pipeline.positionActors()
        self._drawContext = None
        self._drawHint = ''
        self._segmentChanged()
        self._pollDrawState()

    def _discardContour(self):
        pipeline = self._pendingDraw()
        if not pipeline:
            return
        dialog = qt.QMessageBox(slicer.util.mainWindow())
        dialog.objectName = 'MeniscusDiscardContourDialog'
        dialog.setWindowTitle('Discard unfinished contour?')
        dialog.setText('Discard the unfinished contour? Committed annotations will stay unchanged.')
        discard = dialog.addButton('Discard contour',qt.QMessageBox.DestructiveRole)
        keep = dialog.addButton('Keep drawing',qt.QMessageBox.RejectRole)
        dialog.setDefaultButton(keep)
        dialog.setEscapeButton(keep)
        dialog.exec_()
        if dialog.clickedButton() != discard:
            return
        pipeline.resetPolyData()
        pipeline.actionState = ''
        pipeline.positionActors()
        self._drawContext = None
        self._drawHint = ''
        self._pollDrawState()

    def _escape(self):
        self._discardContour() if self._pendingDraw() else self.setTool('')

    def _installDrawGuards(self):
        interactor = slicer.app.layoutManager().sliceWidget('Red').sliceView().interactorStyle().GetInteractor()
        self._drawObserverTags = {}
        for event in ['LeftButtonPressEvent','LeftButtonReleaseEvent','LeftButtonDoubleClickEvent',
                      'RightButtonPressEvent','RightButtonReleaseEvent','MouseMoveEvent','KeyPressEvent',
                      'MouseWheelForwardEvent','MouseWheelBackwardEvent']:
            tag = interactor.AddObserver(event,self._drawInteraction,2.0)
            self._drawObserverTags[event] = tag
            self._observers.append((interactor,tag))

    def _drawInteraction(self, caller, event):
        command = caller.GetCommand(self._drawObserverTags[event])
        command.SetAbortFlag(0)
        if self._loading or not self.session:
            return
        if event in ('MouseWheelForwardEvent','MouseWheelBackwardEvent') and not caller.GetControlKey() and not caller.GetAltKey():
            command.SetAbortFlag(1)
            self.goSlice(self.currentSlice + (1 if event=='MouseWheelForwardEvent' else -1))
            return
        active = self.editor.activeEffect()
        if not active or active.name != 'Draw':
            return
        pipeline = self._pendingDraw()
        if event == 'LeftButtonPressEvent' and not (caller.GetControlKey() or caller.GetShiftKey() or caller.GetAltKey()):
            if not pipeline:
                self._drawContext = self._drawingTargetContext()
            self._drawHint = ''
        if event == 'RightButtonPressEvent':
            self._rightDrawStart = tuple(caller.GetEventPosition())
            self._rightDrawDragged = False
        elif event == 'MouseMoveEvent' and self._rightDrawStart is not None:
            xy = caller.GetEventPosition()
            if np.linalg.norm(np.asarray(xy)-self._rightDrawStart) > 6:
                self._rightDrawDragged = True
        finishing = event in ('RightButtonReleaseEvent','LeftButtonDoubleClickEvent') or (event=='KeyPressEvent' and caller.GetKeySym() in ('a','Return'))
        if finishing and pipeline:
            # Fail closed even if native grid validation raises inside a VTK callback.
            command.SetAbortFlag(1)
            if (event=='RightButtonReleaseEvent' and self._rightDrawDragged) or not self._validDrawContext(pipeline):
                pipeline.actionState = 'moving'
                if event=='RightButtonReleaseEvent' and self._rightDrawDragged:
                    self._drawHint = 'Contour kept. Use Ctrl+wheel to zoom; right-click without dragging to finish.'
                self._updateGuidance()
            else:
                command.SetAbortFlag(0)
        if event == 'RightButtonReleaseEvent':
            self._rightDrawStart = None
            self._rightDrawDragged = False
        # Run after the native effect has handled this event, for immediate feedback.
        qt.QTimer.singleShot(0,self._pollDrawState)

    def _removeDrawMarkers(self):
        if self._drawMarkers:
            self._drawMarkers[0].RemoveActor2D(self._drawMarkers[1])
            self._drawMarkers = None

    def _updateDrawMarkers(self, pipeline):
        if not pipeline:
            self._removeDrawMarkers()
            return
        if not self._drawMarkers or self._drawMarkers[-1] is not pipeline:
            self._removeDrawMarkers()
            # Display-only glyphs share native XY points; native rasterization data
            # and RAS coordinates are never changed by this feedback actor.
            data = vtk.vtkPolyData()
            data.SetPoints(pipeline.xyPoints)
            glyph = vtk.vtkVertexGlyphFilter()
            glyph.SetInputData(data)
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputConnection(glyph.GetOutputPort())
            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.,.95,.45)
            actor.GetProperty().SetPointSize(5)
            renderer = slicer.app.layoutManager().sliceWidget('Red').sliceView().renderWindow().GetRenderers().GetFirstRenderer()
            renderer.AddActor2D(actor)
            self._drawMarkers = (renderer,actor,data,glyph,mapper,pipeline)
            pipeline.actor.GetProperty().SetColor(1.,.95,.45)
        color = (REGIONAL_LABELS.get(self._editingTargetID()) or LABELS.get(self.activeLabel))[1]
        self._drawMarkers[1].GetProperty().SetColor(*color)
        pipeline.actor.GetProperty().SetColor(*color)
        pipeline.actor.GetProperty().SetLineWidth(2)
        self._drawMarkers[2].Modified()

    def _pollDrawState(self):
        if self._loading:
            return
        pipeline = self._pendingDraw()
        count = pipeline.rasPoints.GetNumberOfPoints() if pipeline else 0
        active = self.editor.activeEffect() if self.session else None
        view = slicer.app.layoutManager().sliceWidget('Red')
        state = (id(pipeline),count,active.name if active else '',view.mrmlSliceNode().GetMTime())
        if state == self._drawState:
            return
        self._drawState = state
        self._updateDrawMarkers(pipeline)
        if not count:
            self._drawContext = None
            self._drawHint = ''
        if self.session:
            self.refreshReview()
        else:
            self._updateGuidance()
        view.sliceView().scheduleRender()

    def _configureEffects(self):
        for name in ['Paint', 'Erase']:
            effect = self.editor.effectByName(name)
            for param, value in [('BrushSphere',0), ('BrushPixelMode',0), ('BrushDiameterIsRelative',0), ('EditIn3DViews',0), ('BrushAbsoluteDiameter',self.brushSize.value)]:
                effect.setParameter(param, value)

    def _nativePlane(self, k, reset=False):
        if not self.volume:
            return
        a = self.session.case.affine_ras
        frame = acquired_display_frame(a)
        horizontal,up,normal = frame[:,0],frame[:,1],frame[:,2]
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
        if k == self.currentSlice and self._onAcquiredPlane():
            # Pan/zoom/focus can modify the slice node without leaving its plane.
            # Reprojecting the same plane introduces roundoff that native Draw's
            # exact activeSliceOffset comparison mistakes for a different slice.
            return
        if k != self.currentSlice and self._pendingDraw():
            self._nativePlane(self.currentSlice)
            self._guardContour('changing slices')
            return
        self.goSlice(k)

    def _onAcquiredPlane(self):
        a = self.session.case.affine_ras
        frame = acquired_display_frame(a)
        matrix = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceNode().GetSliceToRAS()
        actual = np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
        k = (np.linalg.inv(a) @ actual[:,3])[2]
        return np.allclose(actual[:3,:3],frame,atol=1e-7,rtol=0) and abs(k-self.currentSlice) < 1e-6

    def goSlice(self, k):
        if not self.session:
            return
        k = int(np.clip(k,0,self.session.case.n_slices-1))
        if k == self.currentSlice and self._pendingDraw() and self._onAcquiredPlane():
            self.refreshReview()
            return True
        if k != self.currentSlice and not self._guardContour('changing slices'):
            self.refreshReview()
            return False
        self.currentSlice = k
        self.session.state['last_slice'] = k
        self._nativePlane(k)
        self.refreshReview()
        if not self._loading:
            self.settings.setValue('Meniscus/slice/' + self.session.case.identity, k)
            self.settings.sync()  # Resume position does not alter an approved annotation.
        return True

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

    def collectRegionalArrays(self):
        whole,_ = self.collectArrays()
        regions = initialize_regions(whole)
        occupied = np.zeros(whole.shape,dtype=bool)
        for region in REGIONS:
            mask = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,region['id'],self.volume).astype(bool)
            parent_value = 1 if region['parent'] == 'medial' else 2
            if np.any(mask & (whole != parent_value)) or np.any(mask & occupied):
                raise ValidationError('A regional assignment conflicts with its whole-meniscus parent. Reopen the latest verified checkpoint.')
            regions[mask] = region['value']
            occupied |= mask
        uncertain = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'regional_uncertain',self.volume).astype(np.uint8)
        if np.any((uncertain != 0) & (whole == 0)):
            raise ValidationError('Regional uncertainty extends outside the whole menisci. Reopen the latest verified checkpoint.')
        return regions,uncertain

    def _segmentChanged(self, *args):
        self._editQueued = False
        if self._loading or self._updating or not self.session:
            return
        self._updating = True
        try:
            # The existing whole-mask identities and independent uncertainty stay
            # fixed. Native Undo snapshots include the regional segments too.
            medial = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'medial',self.volume).astype(bool)
            lateral = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'lateral',self.volume).astype(bool)
            overlap = medial & lateral
            if overlap.any():
                if self.annotationTask != 'whole' or self.activeLabel not in ('medial','lateral'):
                    raise ValidationError('Anatomical overlap detected. Reopen the latest verified checkpoint.')
                other = 'lateral' if self.activeLabel == 'medial' else 'medial'
                other_array = lateral if other == 'lateral' else medial
                slicer.util.updateSegmentBinaryLabelmapFromArray((other_array & ~overlap).astype(np.uint8),self.anatomy,other,self.volume)
            arrays = self.collectArrays()
            binaries = {r['id']:slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,r['id'],self.volume).astype(bool) for r in REGIONS}
            corrected = {}
            selected = self._editingTargetID() if self.annotationTask == 'regions' and not self._regionBoundary else None
            for region in REGIONS:
                key = region['id']
                parent_value = 1 if region['parent'] == 'medial' else 2
                mask = binaries[key] & (arrays[0] == parent_value)
                if selected and selected != key:
                    mask &= ~binaries[selected]
                corrected[key] = mask
            occupied = np.zeros(arrays[0].shape,dtype=bool)
            region_array = initialize_regions(arrays[0])
            for region in REGIONS:
                key = region['id']
                mask = corrected[key]
                if np.any(occupied & mask):
                    raise ValidationError('Regional labels overlap. Reopen the latest verified checkpoint.')
                occupied |= mask
                region_array[mask] = region['value']
                if not np.array_equal(mask,binaries[key]):
                    slicer.util.updateSegmentBinaryLabelmapFromArray(mask.astype(np.uint8),self.anatomy,key,self.volume)
            regional_uncertain = slicer.util.arrayFromSegmentBinaryLabelmap(self.anatomy,'regional_uncertain',self.volume).astype(np.uint8)
            contained_uncertain = (regional_uncertain.astype(bool) & (arrays[0] != 0)).astype(np.uint8)
            if not np.array_equal(contained_uncertain,regional_uncertain):
                slicer.util.updateSegmentBinaryLabelmapFromArray(contained_uncertain,self.anatomy,'regional_uncertain',self.volume)
            previous_whole = self._lastArrays[0] if self._lastArrays is not None else arrays[0]
            # Drawing, or native Undo, can restore tissue to a region previously
            # recorded absent. Require a fresh assessment rather than retaining
            # a contradictory absence or inferring anatomical presence.
            for region in REGIONS:
                assessment = self.regionalState['assessments'][region['id']]
                if assessment['status'] == 'absent' and np.any(region_array == region['value']):
                    assessment['status'] = 'unassessed'
            region_array,contained_uncertain,self.regionalState = reconcile_regions(arrays[0],region_array,contained_uncertain,self.regionalState,previous_whole=previous_whole)
            changed = [int(k) for k in np.flatnonzero(np.any((arrays[0] != self._lastArrays[0]) | (arrays[1] != self._lastArrays[1]),axis=(1,2)))]
            regional_changed = False
            if self._lastRegionalArrays is not None:
                delta = (region_array != self._lastRegionalArrays[0]) | (contained_uncertain != self._lastRegionalArrays[1])
                for parent,value,unassigned in [('medial',1,7),('lateral',2,8)]:
                    relevant = (arrays[0] == value) | (previous_whole == value) | (self._lastRegionalArrays[0] == unassigned)
                    indices = [int(k) for k in np.flatnonzero(np.any(delta & relevant,axis=(1,2)))]
                    if indices:
                        self.regionalState = invalidate_regional_review(self.regionalState,indices,(parent,))
                        regional_changed = True
                whole_uncertainty_changed = [int(k) for k in np.flatnonzero(np.any(arrays[1] != self._lastArrays[1],axis=(1,2)))]
                if whole_uncertainty_changed:
                    self.regionalState = invalidate_regional_review(self.regionalState,whole_uncertainty_changed)
            if changed:
                self.session.mark_changed(changed)
            if changed or regional_changed:
                self.dirty = True
            if self.annotationTask=='whole' and self.activeLabel in ('medial','lateral') and self._lastArrays is not None:
                selected_value = 1 if self.activeLabel=='medial' else 2
                other_value = 3-selected_value
                transferred = int(np.count_nonzero((self._lastArrays[0]==other_value) & (arrays[0]==selected_value)))
                if transferred:
                    self._transferNotice = str(transferred) + ' voxels transferred from ' + ('Lateral' if other_value==2 else 'Medial') + ' to ' + self.activeLabel.capitalize() + '. Inspect the boundary; Undo is available.'
                    self._transferToken += 1
                    token = self._transferToken
                    qt.QTimer.singleShot(9000,lambda:self._clearTransfer(token))
            self._lastArrays = tuple(a.copy() for a in arrays)
            self._lastRegionalArrays = (region_array.copy(),contained_uncertain.copy())
            if changed or regional_changed:
                self.refreshReview()
        except Exception:
            self.editor.setActiveEffectByName('')
            raise
        finally:
            self._updating = False

    def _parentCompartment(self):
        return self.activeLabel if self.activeLabel in ('medial','lateral') else self._lastCompartment

    def _selectedRegionID(self):
        return self._parentCompartment() + '_' + self.activeRegion

    def _editingTargetID(self):
        if self.annotationTask == 'regions':
            return 'regional_uncertain' if self._regionBoundary else self._selectedRegionID()
        return self.activeLabel

    def _drawingTargetContext(self):
        return (self.session.case.identity,self.currentSlice,self._parentCompartment(),
                self.annotationTask,self._editingTargetID())

    def _applyEditingTarget(self):
        if not self.session:
            return
        current = self.editor.activeEffect().name if self.editor.activeEffect() else ''
        self.editor.setCurrentSegmentID(self._editingTargetID())
        if self.annotationTask == 'regions':
            self.editorNode.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedInsideSingleSegment)
            self.editorNode.SetMaskSegmentID(self._parentCompartment())
        else:
            self.editorNode.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedEverywhere)
            self.editorNode.SetMaskSegmentID('')
        self.editor.setActiveEffectByName(current)
        self._configureEffects()

    def _rememberTarget(self):
        if not self.session or self._loading:
            return
        prefix = 'Meniscus/target/' + self.session.case.identity + '/'
        self.settings.setValue(prefix + 'task',self.annotationTask)
        self.settings.setValue(prefix + 'compartment',self._parentCompartment())
        self.settings.setValue(prefix + 'region',self.activeRegion)
        self.settings.sync()

    def _taskChanged(self, index):
        self._safe(lambda:self.setAnnotationTask('regions' if index else 'whole'))

    def setAnnotationTask(self, task):
        if task not in ('whole','regions') or not self.session:
            return False
        if task != self.annotationTask and not self._guardContour('changing annotation tasks'):
            self.taskCombo.blockSignals(True)
            self.taskCombo.setCurrentIndex(1 if self.annotationTask == 'regions' else 0)
            self.taskCombo.blockSignals(False)
            self.taskSelector.sync()
            return False
        if task == self.annotationTask and self._pendingDraw():
            return True
        self._segmentChanged()
        self._workflowHint = ''
        self.annotationTask = task
        self._regionBoundary = False
        if task == 'regions' and self.activeLabel == 'uncertain':
            self.activeLabel = self._lastCompartment
        self.taskCombo.blockSignals(True)
        self.taskCombo.setCurrentIndex(1 if task == 'regions' else 0)
        self.taskCombo.blockSignals(False)
        self.taskSelector.sync()
        self.regionPanel.setVisible(task == 'regions')
        self.regionalAssessmentPanel.setVisible(task == 'regions')
        self.notesPanel.setVisible(task == 'whole')
        self.labelButtons['uncertain'].setVisible(task == 'whole')
        self.showRegions.setChecked(task == 'regions')
        self.approveButton.setEnabled(task == 'whole')
        self.approveButton.setToolTip('Regional approval is unavailable until an expert-defined regional protocol is supplied.' if task == 'regions' else 'Approval is separate from saving and requires every acquired slice to be reviewed.')
        self._applyEditingTarget()
        self._refreshRegionalControls()
        self._rememberTarget()
        self._toolStatus()
        self.refreshReview()
        return True

    def _regionChanged(self, index):
        self._safe(lambda:self.setRegion(('anterior','body','posterior')[index]))

    def setRegion(self, region):
        if region not in ('anterior','body','posterior') or not self.session:
            return False
        if (region != self.activeRegion or self._regionBoundary) and not self._guardContour('changing regions'):
            self.regionCombo.blockSignals(True)
            self.regionCombo.setCurrentIndex(('anterior','body','posterior').index(self.activeRegion))
            self.regionCombo.blockSignals(False)
            self.regionSelector.sync()
            return False
        if region == self.activeRegion and not self._regionBoundary and self._pendingDraw():
            return True
        self._segmentChanged()
        self._workflowHint = ''
        self.activeRegion = region
        self._regionBoundary = False
        self.regionCombo.blockSignals(True)
        self.regionCombo.setCurrentIndex(('anterior','body','posterior').index(region))
        self.regionCombo.blockSignals(False)
        self.regionSelector.sync()
        self._applyEditingTarget()
        self._refreshRegionalControls()
        self._rememberTarget()
        self._toolStatus()
        return True

    def _boundaryUncertain(self):
        if not self.session or self.annotationTask != 'regions':
            return
        if not self._guardContour('changing the regional uncertainty target'):
            self.boundaryUncertainButton.setChecked(self._regionBoundary)
            return False
        self._segmentChanged()
        self._workflowHint = ''
        self._regionBoundary = not self._regionBoundary
        self._applyEditingTarget()
        self._toolStatus()
        return True

    def _refreshRegionalControls(self):
        if not self.regionalState or not self.session:
            return
        assessment = self.regionalState['assessments'][self._selectedRegionID()]
        self.regionStatusCombo.blockSignals(True)
        self.regionStatusCombo.setCurrentIndex(('unassessed','present','absent','uncertain').index(assessment['status']))
        self.regionStatusCombo.blockSignals(False)
        self.assessmentSelector.sync()
        assessment_target = self._parentCompartment().capitalize() + ' · ' + {'anterior':'Anterior horn','body':'Body','posterior':'Posterior horn'}[self.activeRegion]
        self.regionalAssessmentPanel.text = assessment_target
        self.regionalAssessmentPanel.setAccessibleName(assessment_target + ' assessment')
        self.regionalAssessmentPanel.setToolTip(assessment_target + ' assessment. Body is assigned within the complete meniscus, not instead of whole-meniscus correction.')
        self.regionLegend.setText('<br>'.join('<span style="color:' + qt.QColor.fromRgbF(*REGIONAL_COLORS[index + (0 if self._parentCompartment()=="medial" else 3)]).name() + '">━━</span> ' + name for index,name in enumerate(['AH · Anterior horn','B · Body','PH · Posterior horn'])))
        note = assessment.get('note','')
        if str(self.regionNotes.toPlainText()) != note:
            self.regionNotes.blockSignals(True)
            self.regionNotes.setPlainText(note)
            self.regionNotes.blockSignals(False)
        self.regionalFlag.blockSignals(True)
        self.regionalFlag.setChecked(bool(self.regionalState['review'][self.currentSlice]['flag']))
        self.regionalFlag.blockSignals(False)
        regions, uncertainty = self._lastRegionalArrays if self._lastRegionalArrays is not None else self.collectRegionalArrays()
        value = 7 if self._parentCompartment() == 'medial' else 8
        counts = np.bincount(regions.ravel(),minlength=9)
        assessments = self.regionalState['assessments']
        reviews = self.regionalState['review']
        reviewed = all(row['medial_reviewed'] and row['lateral_reviewed'] and not row['flag'] for row in reviews)
        considered = all(assessments[item['id']]['status'] == ('present' if counts[item['value']] else 'absent') for item in REGIONS)
        whole_uncertain = self._lastArrays[1] if self._lastArrays is not None else self.collectArrays()[1]
        complete = reviewed and considered and not counts[7:9].sum() and not uncertainty.any() and not whole_uncertain.any()
        started = bool(counts[1:7].sum() or uncertainty.any() or any(row['medial_reviewed'] or row['lateral_reviewed'] or row['flag'] for row in reviews) or any(item['status'] != 'unassessed' or item['note'] for item in assessments.values()))
        status = 'Draft reviewed' if complete else ('In progress' if started else 'Not assigned')
        self.regionalProtocolLabel.setText(status + ' · Protocol pending')
        self.regionalSummary.setText(f'{int(counts[value])} unassigned voxels in this meniscus. Regional research approval is unavailable while the protocol is pending.')

    def _regionalChanged(self):
        if self._loading or not self.session:
            return
        self.dirty = True
        self.regionalState['status'] = 'draft'
        self.regionalState['research_approved'] = False
        self.refreshReview()

    def _regionalAssessmentChanged(self, index):
        if self._loading or not self.regionalState or not self.session:
            return
        key = self._selectedRegionID()
        status = ('unassessed','present','absent','uncertain')[index]
        if self.regionalState['assessments'][key]['status']==status:
            return
        if status == 'absent':
            regions,_ = self.collectRegionalArrays()
            value = next(item['value'] for item in REGIONS if item['id'] == key)
            if np.any(regions == value):
                self._refreshRegionalControls()
                slicer.util.infoDisplay('This region still has assigned voxels. Erase those assignments before recording the region as absent. Whole-meniscus tissue is preserved.',windowTitle='Region assessment')
                return
        self.regionalState['assessments'][key]['status'] = status
        self._regionalChanged()
        if status=='present':
            value = next(item['value'] for item in REGIONS if item['id']==key)
            if not np.any(self._lastRegionalArrays[0]==value):
                self._workflowHint = 'Present is recorded, but this region has no assigned voxels. Assign the region or revise its assessment before completing regional review.'
                self._updateGuidance()

    def _regionalNoteChanged(self):
        if self._loading or not self.regionalState or not self.session:
            return
        self.regionalState['assessments'][self._selectedRegionID()]['note'] = str(self.regionNotes.toPlainText())
        self._regionalChanged()

    def _regionalFlagChanged(self, checked):
        if self._loading or not self.regionalState or not self.session:
            return
        self.regionalState['review'][self.currentSlice]['flag'] = bool(checked)
        self._regionalChanged()

    def setLabel(self, key):
        if not self.session:
            return
        if key == 'uncertain' and self.annotationTask == 'regions':
            self._workflowHint = 'Uncertain area belongs to Whole meniscus. Choose Whole meniscus, or use Boundary uncertain for regions.'
            self._updateGuidance()
            return False
        if key != self.activeLabel and not self._guardContour('changing compartments'):
            self._toolStatus()
            return False
        if key == self.activeLabel and self._pendingDraw():
            self._toolStatus()
            return True
        self._segmentChanged()
        self._workflowHint = ''
        if self._windowLevelActive:
            self.setTool('Draw')
        self.activeLabel = key
        if key in ('medial','lateral'):
            self._lastCompartment = key
        previousTool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Draw'
        if self.editor.segmentationNode() != self.anatomy:
            self.editor.setSegmentationNode(self.anatomy)
        self._applyEditingTarget()
        self.editor.setActiveEffectByName(previousTool)
        for k, b in self.labelButtons.items():
            b.setChecked(k == key)
        self.labelCombo.blockSignals(True)
        self.labelCombo.setCurrentIndex(list(LABELS).index(key))
        self.labelCombo.blockSignals(False)
        self._refreshRegionalControls()
        self._rememberTarget()
        self._toolStatus()

    def setTool(self, name):
        if not self.session:
            return
        current = self.editor.activeEffect().name if self.editor.activeEffect() else ''
        if name != current and not self._guardContour('changing tools'):
            self._toolStatus()
            return False
        if name == current and self._pendingDraw():
            self._toolStatus()
            return True
        self._segmentChanged()
        self._workflowHint = ''
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
        if not self._guardContour('adjusting window/level'):
            self.windowLevelButton.setChecked(False)
            return False
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
        if not self.session:
            self._updateGuidance()
            return
        if self._windowLevelActive:
            tool = 'Window/level'
            self.toolText.setText('Window/level · Display only')
        else:
            tool = self.editor.activeEffect().name if self.editor.activeEffect() else 'Navigate'
            self.toolText.setText('This acquired slice only' if tool != 'Navigate' else 'Navigate · No drawing')
        self.toolText.setText(('Within selected meniscus · ' if self.annotationTask == 'regions' else '') + ('Acquired slice only' if tool != 'Navigate' and not self._windowLevelActive else str(self.toolText.text)))
        self.toolText.setToolTip((REGIONAL_LABELS[self._editingTargetID()][0] if self.annotationTask == 'regions' else LABELS[self.activeLabel][0]) + ' · ' + tool)
        self.boundaryUncertainButton.setChecked(self._regionBoundary)
        for name, button in self.toolButtons.items():
            button.setChecked(name == tool)
        for key, button in self.labelButtons.items():
            button.setChecked(key == self.activeLabel)
        self.brushRow.setVisible(tool in ('Paint','Erase'))
        self._refreshIdentity()
        self._updateGuidance()
        annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
        annotation.SetText(vtk.vtkCornerAnnotation.UpperRight,'')
        slicer.app.layoutManager().sliceWidget('Red').sliceView().forceRender()

    def _brush(self, *args):
        self.settings.setValue('Meniscus/brush', self.brushSize.value)
        if self.session:
            self._configureEffects()
            self._toolStatus()

    def _clearTransfer(self, token=None):
        if token is None or token==self._transferToken:
            self._transferNotice = ''
            self._updateGuidance()

    def _showPlausibility(self):
        if self._plausibility:
            slicer.util.infoDisplay(self._plausibility['message'] + '\n\nThis is a simple physical-position prompt, not anatomical validation. Tiny, absent or unusual masks may be inconclusive. No voxels have been swapped or removed.',windowTitle='Inspect medial/lateral labels')

    def _undo(self):
        if self.session and self._guardContour('undoing a committed edit'):
            self._transferNotice = ''
            self.editor.undo()
            self._segmentChanged()

    def _redo(self):
        if self.session and self._guardContour('redoing a committed edit'):
            self.editor.redo()
            self._segmentChanged()

    def _display(self, *args):
        self.opacity.setEnabled(self.fill.checked)
        self.settings.setValue('Meniscus/fill',bool(self.fill.checked))
        self.settings.setValue('Meniscus/opacity',self.opacity.value)
        self.settings.setValue('Meniscus/outlineWidth',self.outlineWidth.value)
        if not self.anatomy:
            return
        for node in [self.anatomy]:
            d = node.GetDisplayNode()
            d.SetVisibility(self.visible.checked)
            d.SetOpacity2DFill(self.opacity.value/100 if self.fill.checked else 0)
            d.SetOpacity2DOutline(1)
            d.SetSliceIntersectionThickness(int(self.outlineWidth.value))
            for key in LABELS:
                d.SetSegmentVisibility(key,True)
                d.SetSegmentOpacity2DFill(key,0 if self.showRegions.checked and key in ('medial','lateral') else 1)
            for key in REGIONAL_LABELS:
                d.SetSegmentVisibility(key,bool(self.showRegions.checked))
                d.SetSegmentOpacity2DFill(key,1)

    def _layoutViews(self, *args):
        if self.session and not self._guardContour('changing the view layout'):
            self.reformats.blockSignals(True)
            self.reformats.setChecked(slicer.app.layoutManager().layout == 703)
            self.reformats.blockSignals(False)
            return False
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
        if self.session and self._guardContour('resetting the view'):
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
            text = str(self.notes.toPlainText())
            if text != self.session.state['notes']:
                self.session.state['notes'] = text
                self._changed()

    def _compartments(self, *args):
        if self.session and not self._loading:
            value = {'medial': self.medialConsidered.checked, 'lateral': self.lateralConsidered.checked}
            if value != self.session.state['compartments']:
                self.session.state['compartments'] = value
                self._changed()

    def _flag(self, checked):
        if self.session and not self._loading:
            row = self.session.state['review'][self.currentSlice]
            if row['flag'] != bool(checked):
                row['flag'] = bool(checked)
                self._changed()

    def _reviewNext(self):
        if not self.session or not self._guardContour('marking the slice reviewed'):
            return
        if self._editQueued:
            self._segmentChanged()
        self._assertGrid()
        regional = self.annotationTask=='regions'
        changed = self.session.mark_reviewed(self.currentSlice,compartment=self._parentCompartment() if regional else None,regional_state=self.regionalState if regional else None)
        if changed:
            self.dirty = True
            if self._safe(self._persistReview) is None:
                return
        self.goSlice(self.currentSlice+1)
        self._updateCurrentStatus()
        self._updateGuidance()

    def _persistReview(self):
        # The native source observers keep these exact arrays current. Review
        # alone does not repeatedly pull ten full-volume native labelmaps.
        arrays = self._lastArrays
        regions,regional_uncertain = self._lastRegionalArrays
        self.saveStatus.setText(('Practice · ' if self._isPractice() else '') + 'Saving…')
        self.saveStatus.repaint()
        try:
            if self.session.can_journal_review(arrays[0],arrays[1],regions=regions,regional_uncertainty=regional_uncertain):
                path = self.session.save_review_journal(arrays[0],arrays[1],regional_state=self.regionalState,regions=regions,regional_uncertainty=regional_uncertain)
                self.dirty = False
                self._saveError = False
                self._reviewOnlyDirty = True
                self.refreshReview()
                self.saveStatus.setToolTip('Saved in a recoverable review record. Save draft or approval creates a full checkpoint; no earlier checkpoint was changed.')
                return path
            return self.save()
        except Exception:
            self.dirty = True
            self._saveError = True
            self.saveStatus.setText('Save failed')
            self.saveStatus.setToolTip('The review mark is still unsaved. Check disk space and work-folder permissions, then retry Save draft.')
            raise

    def _updateCurrentStatus(self):
        if not self.session or not self.dataset:
            return
        for row in range(self.caseTable.rowCount):
            if self.caseTable.item(row,0).data(qt.Qt.UserRole)==self.session.case.key:
                text = status_label(self.session.state,uncertainty=self._lastArrays[1])
                self.caseTable.item(row,1).setText(text)
                break
        self._filter()

    def _jump(self, predicate):
        if self.session:
            n = self.session.case.n_slices
            records = self.regionalState['review'] if self.annotationTask == 'regions' else self.session.state['review']
            for step in range(1,n+1):
                k = (self.currentSlice+step)%n
                if predicate(records[k]):
                    self.goSlice(k)
                    return
            self.message.setText('No matching slices.')

    def _nextUnreviewed(self):
        key = self._parentCompartment() + '_reviewed' if self.annotationTask == 'regions' else 'reviewed'
        self._jump(lambda r: not r[key])

    def _nextFlagged(self):
        self._jump(lambda r: r['flag'])

    def refreshReview(self):
        if not self.session:
            return
        m = self.session.case.metadata
        self._refreshIdentity()
        correction = self.session.state['initialization']['method'] == 'correction'
        self.initializationLabel.setText('Correction · Unreviewed starting mask' if correction else 'Blank annotation · No starting mask')
        self.initializationLabel.setToolTip('Starting masks are unreviewed model predictions. Check both compartments throughout the acquired stack.' if correction else 'This case was intentionally initialized with empty labels.')
        regional = self.annotationTask == 'regions'
        review = self.regionalState['review'] if regional else self.session.state['review']
        review_key = self._parentCompartment() + '_reviewed' if regional else 'reviewed'
        count = sum(bool(r[review_key]) for r in review)
        flags = sum(bool(r['flag']) for r in review)
        self.progress.setText((self._parentCompartment().capitalize() + ' regions · ' if regional else '') + f'{count} of {len(review)} reviewed · {flags} flagged')
        self.progress.setToolTip(str(self.progress.text))
        self.jumpButton.setToolTip(str(self.progress.text) + ' · Jump to an unreviewed or flagged slice')
        direction = slice_direction(self.session.case.affine_ras,m['knee_side'])
        cue = ('Next → ' + direction['toward']) if direction['toward']!='ambiguous' else 'Next → oblique'
        self.sliceReadout.setText(f'Slice {self.currentSlice+1} of {len(review)}\n' + cue)
        self.sliceReadout.setToolTip(direction['explanation'] + ' Displayed slice 1 is stored array k=0; increasing slice numbers follow the original stored K direction.')
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
        state = 'Reviewed' if review[self.currentSlice][review_key] else 'Not reviewed'
        self.sliceState.setText(state + (' · Flagged' if review[self.currentSlice]['flag'] else ''))
        self.sliceState.setToolTip(('Regional review · ' + self._parentCompartment()) if regional else 'Whole-meniscus slice review')
        context = self._updatePracticeContext()
        save_text = 'Save failed' if self._saveError else ('Unsaved contour' if self._pendingDraw() else ('Unsaved changes' if self.dirty else ('Saved' if self.session.current_checkpoint else 'New draft')))
        self.saveStatus.setText(('Practice · ' if self._isPractice() else '') + save_text)
        self.saveStatus.setToolTip('Saving preserves a draft. It does not mark a slice reviewed or approve a case.')
        status = status_label(self.session.state,uncertainty=self._lastArrays[1])
        self.approvalStateLabel.setText('Whole meniscus · ' + status)
        self.approveButton.setText('Approve practice case' if self._isPractice() else 'Approve case')
        self.plausibilityButton.setVisible(bool(self._plausibility and self._plausibility['status']=='check'))
        self._updateCurrentStatus()
        self._refreshRegionalControls()
        annotation = slicer.app.layoutManager().sliceWidget('Red').sliceView().cornerAnnotation()
        annotation.SetText(vtk.vtkCornerAnnotation.UpperLeft,'')
        self._updateGuidance()

    def _segWriter(self, path):
        # One editable segmentation contains all fixed IDs. Separate layers preserve uncertainty overlap.
        combined = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Checkpoint')
        combined.SetReferenceImageGeometryParameterFromVolumeNode(self.volume)
        try:
            for node, ids in [(self.anatomy,list(LABELS) + list(REGIONAL_LABELS))]:
                for key in ids:
                    if not combined.GetSegmentation().CopySegmentFromSegmentation(node.GetSegmentation(),key):
                        raise ValidationError('Could not preserve the editable segmentation.')
                    segment = combined.GetSegmentation().GetSegment(key)
                    segment.SetTag('annotation_purpose',annotation_purpose(self.session.state))
                    approving,practice = getattr(self,'_savingApproval',(False,False))
                    eligible = research_eligible(self.session.state) or (approving and not practice and self.session.state['protocol']['status']=='released' and not self.session.state.get('practice_context'))
                    segment.SetTag('research_eligible','true' if key in ('medial','lateral') and eligible else 'false')
                    segment.SetTag('application_version',VERSION)
                    if key in REGIONAL_LABELS:
                        segment.SetTag('regional_protocol_status','pending')
            storage = combined.CreateDefaultStorageNode()
            slicer.mrmlScene.AddNode(storage)
            combined.SetAndObserveStorageNodeID(storage.GetID())
            storage.SetCropToMinimumExtent(False)
            if not slicer.util.saveNode(combined, str(path)):
                raise OSError('Could not write the editable segmentation. Check disk space and permissions.')
            # Reopen with Slicer's independent storage reader and compare against full reference arrays.
            reopened = slicer.util.loadSegmentation(str(path))
            try:
                for key in list(LABELS) + list(REGIONAL_LABELS):
                    node = self.anatomy
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
        if not self._guardContour('saving'):
            return
        self._segmentChanged()
        self._assertGrid()
        import hashlib
        if hashlib.sha256(slicer.util.arrayFromVolume(self.volume).tobytes()).hexdigest() != self._volumeDigest:
            self.editor.setActiveEffectByName('')
            raise ValidationError('The loaded source image pixels changed. Reopen the case before saving.')
        self.saveStatus.setText(('Practice · ' if self._isPractice() else '') + 'Saving…')
        self.saveStatus.repaint()
        labels, uncertain = self.collectArrays()
        self.session.state['runtime'] = {'slicer_version':slicer.app.applicationVersion, 'slicer_revision':slicer.app.repositoryRevision, 'application_version':VERSION, 'interface_revision':'reader-repair-0.2', **SOURCE_IDENTITY}
        regions, regional_uncertain = self.collectRegionalArrays()
        self._savingApproval = (bool(approve),bool(practice))
        try:
            path = self.session.save(labels, uncertain, self._segWriter, approve=approve, practice=practice,regions=regions,regional_uncertainty=regional_uncertain,regional_state=self.regionalState)
        except Exception:
            self.dirty = True
            self._saveError = True
            self.saveStatus.setText('Save failed')
            self.saveStatus.setToolTip('Unsaved changes. Check disk space and work-folder permissions, then retry Save draft.')
            raise
        self.regionalState = self.session.regional_state
        self.dirty = False
        self._saveError = False
        self._reviewOnlyDirty = False
        self.refreshReview()
        self._populate()
        self.saveStatus.setText(('Practice · ' if self._isPractice() else '') + 'Saved')
        return path

    def _approve(self):
        if not self.session:
            return
        if self.annotationTask == 'regions':
            slicer.util.infoDisplay('Regional research approval is unavailable until an expert-defined regional protocol is supplied. Use Save draft to preserve regional work.',windowTitle='Regional protocol pending')
            return
        if not self._guardContour('approving the case'):
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
        if self._pendingDraw():
            return  # An unfinished contour is visibly unsaved; never dismiss it for autosave.
        if self.session and self.dirty:
            try:
                self.save()
            except Exception:
                self._diagnostic = traceback.format_exc()
                self._saveError = True
                self.saveStatus.setText('Save failed')
                self.saveStatus.setToolTip('Autosave failed. Previous checkpoints are intact. Check disk space and work-folder permissions, then use Save draft.')
                self.message.setText('Check disk space and work-folder permissions, then use Save draft. Previous checkpoints are intact.')

    def _showWork(self):
        if self.store:
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(self.store.root)))

    def _exportDialog(self):
        if not self.store or not self._guardContour('exporting'):
            return
        if self.session and (self.dirty or getattr(self.session,'review_journal_pending',False)):
            if self._safe(self.save) is None:
                return
        chosen_rows = sorted({index.row() for index in self.caseTable.selectedIndexes()})
        chosen_keys = [self.caseTable.item(row,0).data(qt.Qt.UserRole) for row in chosen_rows]
        dialog = qt.QDialog(slicer.util.mainWindow())
        dialog.objectName = 'MeniscusExportDialog'
        dialog.setWindowTitle('Export results')
        dialog.setStyleSheet(self.style)
        dialog.resize(860,520)
        dialog.setMinimumSize(720,380)
        layout = qt.QVBoxLayout(dialog)
        heading = qt.QLabel('Review the exact cases and versions to return. MRI images are not included.')
        heading.wordWrap = True
        layout.addWidget(heading)
        selected = qt.QCheckBox('Selected cases only ('+str(len(chosen_keys))+')')
        selected.objectName = 'MeniscusExportSelectedOnly'
        selected.setEnabled(bool(chosen_keys))
        selected.setToolTip('Select cases in the case list before opening Export.' if not chosen_keys else 'Export only these selected cases; unapproved selections require attention.')
        layout.addWidget(selected)
        practice = qt.QCheckBox('Practice results — not research/training eligible')
        practice.objectName = 'MeniscusExportPractice'
        draft = (self.store.job or {}).get('protocol',{}).get('status','draft')=='draft'
        if self.store.practice_context or draft:
            practice.setChecked(True)
            practice.setEnabled(False)
            practice.setText('Software-practice results only — not research annotations' if self.store.practice_context else 'Practice results only — draft anatomical protocol')
        layout.addWidget(practice)
        earlier = qt.QCheckBox('Explicitly use the earlier approved versions listed below')
        earlier.objectName = 'MeniscusExportEarlier'
        omit = qt.QCheckBox('Exclude cases with newer unapproved work')
        omit.objectName = 'MeniscusExportOmitNewer'
        layout.addWidget(earlier)
        layout.addWidget(omit)
        table = qt.QTableWidget(0,4)
        table.objectName = 'MeniscusExportSummary'
        table.setHorizontalHeaderLabels(['Case','Result','Version','Action / reason'])
        table.verticalHeader().hide()
        table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        table.setWordWrap(True)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table,1)
        message = qt.QLabel('Preparing export summary…')
        message.objectName = 'MeniscusExportSummaryText'
        message.wordWrap = True
        layout.addWidget(message)
        buttons = qt.QDialogButtonBox(dialog)
        buttons.objectName = 'MeniscusExportButtons'
        buttons.setStandardButtons(qt.QDialogButtonBox.Ok | qt.QDialogButtonBox.Cancel)
        export_button = buttons.button(qt.QDialogButtonBox.Ok)
        export_button.objectName = 'MeniscusExportConfirm'
        export_button.setText('Export')
        export_button.setDefault(True)
        buttons.button(qt.QDialogButtonBox.Cancel).objectName = 'MeniscusExportCancel'
        buttons.connect('accepted()',dialog.accept)
        buttons.connect('rejected()',dialog.reject)
        layout.addWidget(buttons)
        state = {'plan':None,'keys':None,'choices':{}}
        def caption(key):
            m = self.dataset.by_key[key].metadata
            return f"OAI {m['participant_id']} · M{int(m['visit_month']):03d} · {'Left' if m['knee_side']=='L' else 'Right'}"
        def refresh(*args):
            keys = chosen_keys if selected.checked else None
            try:
                initial = export_plan(self.store,case_keys=keys,include_practice=practice.checked)
                choices = {row['case_key']:row['approved_checkpoint'] if earlier.checked else None for row in initial['requires_choice']} if earlier.checked or omit.checked else {}
                plan = export_plan(self.store,case_keys=keys,include_practice=practice.checked,earlier_choices=choices)
                state.update(plan=plan,keys=keys,choices=choices)
                earlier.setVisible(bool(initial['requires_choice']))
                omit.setVisible(bool(initial['requires_choice']))
                def version_text(item,checkpoint=None):
                    lines = [('Export: ' if checkpoint else 'Approval: ') + (checkpoint or item.get('approved_checkpoint') or '—')]
                    if item.get('earlier_version') or item in plan['requires_choice']:
                        lines.append('Exclude latest: ' + (item.get('latest_checkpoint') or '—'))
                        journal = item.get('latest_review_journal')
                        if journal:
                            lines.append('Exclude review: ' + journal['record'])
                    return '\n'.join(lines)
                rows = [(item,'Include '+item['status_label'],version_text(item,item['checkpoint']),('Earlier approval explicitly chosen; newer work is excluded.' if item['earlier_version'] else 'Latest approved checkpoint')) for item in plan['included']]
                rows += [(item,'Decision required',version_text(item),item['reason']+' '+item['action']) for item in plan['requires_choice']]
                rows += [(item,'Excluded',item.get('latest_checkpoint') or '—',item['reason']+' '+item['action']) for item in plan['excluded']]
                table.setRowCount(len(rows))
                for row,(item,result,version,action) in enumerate(rows):
                    for col,text in enumerate([caption(item['case_key']),result,version,action]):
                        cell = qt.QTableWidgetItem(text)
                        cell.setToolTip(text)
                        table.setItem(row,col,cell)
                table.resizeColumnsToContents()
                table.setColumnWidth(0,200)
                table.setColumnWidth(1,145)
                table.setColumnWidth(2,180)
                table.resizeRowsToContents()
                blocked = bool(plan['requires_choice']) or (selected.checked and any(item['code']!='explicitly_omitted' for item in plan['excluded']))
                export_button.setEnabled(bool(plan['included']) and not blocked)
                if plan['requires_choice']:
                    message.setText('Newer unapproved work exists. Approve the newest work, explicitly choose the listed earlier approval, or exclude those cases. Nothing will be silently replaced.')
                elif selected.checked and blocked:
                    message.setText('Some selected cases are not eligible. Follow the listed action, or cancel and change the selection. Choose all approved cases to return eligible cases with exclusions listed.')
                elif not plan['included']:
                    message.setText('No eligible approved cases are available. Review the listed reasons. Complete review and approval, then reopen Export; no results folder has been created.')
                else:
                    message.setText(str(len(plan['included']))+' case(s) will be returned; '+str(len(plan['excluded']))+' excluded. '+('PRACTICE ONLY — not research/training eligible.' if practice.checked else 'Research approvals only.'))
            except Exception as exc:
                export_button.setEnabled(False)
                message.setText('The selection could not be verified. '+str(exc))
                self._diagnostic = traceback.format_exc()
        def earlier_changed(value):
            if value:
                omit.blockSignals(True); omit.setChecked(False); omit.blockSignals(False)
            refresh()
        def omit_changed(value):
            if value:
                earlier.blockSignals(True); earlier.setChecked(False); earlier.blockSignals(False)
            refresh()
        selected.connect('toggled(bool)',refresh)
        practice.connect('toggled(bool)',refresh)
        earlier.connect('toggled(bool)',earlier_changed)
        omit.connect('toggled(bool)',omit_changed)
        refresh()
        if dialog.exec_()!=qt.QDialog.Accepted or not state['plan']:
            return
        if self._practiceConfig:
            destination = Path(self._practiceConfig['results_root'])
        else:
            documents = qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)
            target = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(),'Export return ZIP to folder',documents)
            if not target:
                return
            destination = Path(target)/'Meniscus_annotation_results'
        result = self._safe(lambda:export_approved(self.store,destination,case_keys=state['keys'],include_practice=practice.checked,earlier_choices=state['choices'],plan=state['plan']))
        if result:
            self._lastExport = result
            self.message.setText('Export verified: '+Path(result).name)
            notice = qt.QMessageBox(slicer.util.mainWindow())
            notice.objectName = 'MeniscusExportComplete'
            notice.setWindowTitle('Export complete')
            notice.setText('Results ZIP created and checked.\n\n'+Path(result).name)
            notice.setInformativeText(str(len(state['plan']['included']))+' case(s), '+str(len(state['plan']['excluded']))+' excluded. The confirmed checkpoint versions are recorded in results.json.')
            show = notice.addButton('Show exported file',qt.QMessageBox.ActionRole)
            notice.addButton(qt.QMessageBox.Close)
            notice.exec_()
            if notice.clickedButton()==show:
                qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(Path(result).parent)))

    def _help(self):
        text = 'Meniscus Annotator ' + VERSION + '\n\nOpen dataset → Open case → Draw → Review every slice → Save draft → Approve → Export.\n\nWorkspace shortcuts (inactive in text and number fields):\nLeft / Right: acquired slice · R: reviewed and next\nU: next unreviewed · F: next flagged\n1 / 2 / 3: medial / lateral / uncertain\nD / E / P: draw / erase / paint · Esc: discard contour or navigate\nCtrl+S: save · Ctrl+Z / Ctrl+Y: undo / redo\n\nNative Slicer mouse controls:\nCtrl+wheel: zoom · middle drag: pan\nWheel: one acquired slice · Draw reserves right-click for finishing\nWindow/level: choose it in Image and annotation display, then left-drag\nDraw: Click around the boundary. Right-click to close and fill.\nCtrl+wheel zooms while drawing. Right-drag keeps the unfinished contour.\nFinish or explicitly discard a contour before changing slices, labels or tools, or saving. Closing offers Finish contour, Discard contour and Keep drawing. X removes the last point.\n\nEvery changed slice requires review again. Uncertainty is a separate overlapping mask and blocks approval until resolved. Draft protocols allow Practice approved only; Export includes practice by default and identifies it separately. If a newer draft exists, the export dialog requires an explicit earlier-version or omission choice. Whole meniscus corrects complete medial/lateral masks; Regions (draft) assigns anterior horn, body and posterior horn within the selected parent. Regional research approval is unavailable pending expert boundaries. Saved versions recover work after restart; in-memory undo history does not survive restart.\n\nHelp → Troubleshooting includes details of the last error.'
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
            self._diagnostics()

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
        if hasattr(self, 'drawFeedback'):
            self.drawFeedback.stop()
        self.closeCase()
        for name in ['caseListDock','rightDock','topBar','stepBar','bottomBar']:
            widget = getattr(self, name, None)
            if widget:
                widget.hide()
                widget.deleteLater()
