"""Actual Slicer layout/font checks with procedural synthetic inputs only.

Run with MENISCUS_LAYOUT_OUTPUT outside the source tree and
MENISCUS_SETTINGS_FILE=<output>/Workspace.ini. ``layout`` creates a fresh
package/profile; ``persist`` reopens that same profile in a new process.
Injected Qt/VTK interactions are software checks, not human or Windows acceptance.
"""
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

import qt
import slicer
import vtk
import numpy as np

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
if (TEST_DIR.parent / 'MeniscusAnnotatorLib').is_dir():
    sys.path.insert(0, str(TEST_DIR.parent))
from draw_fixture import make_draw_matrix
from MeniscusAnnotatorLib.core import Dataset, sha256

OUTPUT = Path(os.environ['MENISCUS_LAYOUT_OUTPUT']).resolve()
PHASE = os.environ.get('MENISCUS_LAYOUT_PHASE', 'layout')
REPORT = {'phase': PHASE, 'checks': [], 'layouts': [],
          'scope': 'Procedural synthetic actual Slicer desktop; injected Qt/VTK events. Not human, anatomical or Windows display-setting acceptance.'}
WIDGET = None


def events(seconds=.05):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        slicer.app.processEvents()
        time.sleep(.005)


def check(name, value, detail=None):
    item = {'name': name, 'passed': bool(value)}
    if detail is not None:
        item['detail'] = detail
    REPORT['checks'].append(item)
    (OUTPUT / ('progress-' + PHASE + '.json')).write_text(json.dumps(item, indent=2) + '\n')
    return bool(value)


def font_details(control):
    control.ensurePolished()
    font = control.font
    resolved = qt.QFontInfo(font)
    return {'requested_family': font.family(), 'requested_pt': font.pointSizeF(),
            'requested_weight': font.weight(), 'resolved_family': resolved.family(),
            'resolved_pt': resolved.pointSizeF(), 'resolved_weight': resolved.weight(),
            'resolved_bold': resolved.bold(), 'exact_match': resolved.exactMatch()}


def controls(widget):
    result = {'identity':widget.identityLabel, 'save_state':widget.saveStatus,
              'slice':widget.sliceReadout, 'slider':widget.sliceSlider,
              'previous':widget.previousButton, 'next':widget.nextButton,
              'slice_entry':widget.sliceSpin, 'save':widget.saveButton,
              'review':widget.reviewButton, 'instruction':widget.instruction,
              'undo':widget.undoButton, 'redo':widget.redoButton,
              'task':widget.taskCombo, 'active_compartment':widget.annotationTitle,
              'cases_toggle':widget.casesToggle, 'tools_toggle':widget.toolsToggle,
              **{'tool_' + key: value for key,value in widget.toolButtons.items()},
              **{'label_' + key: value for key,value in widget.labelButtons.items()}}
    if widget.annotationTask == 'regions':
        result.update(region=widget.regionCombo, boundary=widget.boundaryUncertainButton)
        result.pop('label_uncertain')
    return result


def geometry(control, window):
    rect = qt.QRect(control.mapTo(window, qt.QPoint(0,0)), control.size)
    clipped = []
    ancestor = control.parentWidget()
    while ancestor is not None and ancestor != window:
        mapped = qt.QRect(control.mapTo(ancestor,qt.QPoint(0,0)),control.size)
        if not ancestor.rect.contains(mapped):
            clipped.append(str(ancestor.objectName) or type(ancestor).__name__)
        ancestor = ancestor.parentWidget()
    return {'visible':control.isVisible(), 'window_rect':[rect.x(),rect.y(),rect.width(),rect.height()],
            'window_contains':window.rect.contains(rect),
            'full_visible_region':control.visibleRegion().boundingRect().contains(control.rect),
            'clipped_ancestors':clipped}


def capture(widget, name, width, height, pending=False):
    window = slicer.util.mainWindow()
    window.resize(width,height)
    events(.25)
    scroll = widget.rightDock.findChild(qt.QScrollArea)
    if scroll:
        scroll.verticalScrollBar().setValue(0)
    events(.1)
    view = slicer.app.layoutManager().sliceWidget('Red').sliceView()
    view.forceRender()
    entry = {'name':name, 'requested_size':[width,height], 'actual_size':[window.width,window.height],
             'dpr':window.devicePixelRatioF(), 'header_height':widget.topBar.height,
             'footer_height':widget.bottomBar.height, 'footer_size_hint':[widget.bottomBar.sizeHint.width(),widget.bottomBar.sizeHint.height()], 'canvas_size':[view.width,view.height],
             'cases_visible':widget.caseListDock.isVisible(), 'tools_visible':widget.rightDock.isVisible(),
             'instruction':str(widget.instruction.text), 'controls':{}}
    screen = window.screen().availableGeometry if hasattr(window,'screen') else qt.QApplication.desktop().availableGeometry(window)
    entry['available_desktop'] = [screen.width(),screen.height()]
    for key,control in controls(widget).items():
        value = geometry(control,window)
        entry['controls'][key] = value
        should_show = key not in ('label_uncertain',) or widget.annotationTask == 'whole'
        panel_control = key in ('task','region','boundary','active_compartment','undo','redo') or key.startswith(('tool_','label_'))
        if panel_control and not widget.rightDock.isVisible():
            should_show = False
        if should_show:
            check(name + ' visible contained ' + key, value['visible'] and value['window_contains'] and value['full_visible_region'] and not value['clipped_ancestors'], value)
    if pending:
        for key,control in [('finish',widget.finishContourButton),('discard',widget.discardContourButton)]:
            value=geometry(control,window)
            entry['controls'][key]=value
            check(name + ' pending ' + key + ' accessible', value['visible'] and value['window_contains'] and value['full_visible_region'] and not value['clipped_ancestors'], value)
    horizontal = [bar for bar in window.findChildren(qt.QScrollBar) if bar.isVisible() and bar.orientation==qt.Qt.Horizontal and bar.maximum>0]
    check(name + ' no horizontal scrolling',not horizontal)
    entry['right_vertical_scroll_range'] = scroll.verticalScrollBar().maximum if scroll else 0
    if scroll:
        def sizes(item):
            def wh(value):
                value=value() if callable(value) else value
                return [value.width(),value.height()]
            result={'class':type(item).__name__,'name':str(item.objectName),
                    'text':str(getattr(item,'text','')),'size':[item.width,item.height],
                    'hint':wh(item.sizeHint),'minimum_hint':wh(item.minimumSizeHint),
                    'minimum':[item.minimumWidth,item.minimumHeight],
                    'horizontal_policy':int(item.sizePolicy.horizontalPolicy())}
            return result
        entry['right_panel']={'dock':sizes(widget.rightDock),'viewport':sizes(scroll.viewport()),
                              'panel':sizes(scroll.widget()),
                              'visible_children':[sizes(child) for child in scroll.widget().findChildren(qt.QWidget) if child.isVisible()]}

    footer = widget.bottomBar.findChild(qt.QWidget,'navigationPanel')
    if footer:
        entry['footer_widget'] = {'size':[footer.width,footer.height],
                                  'hint':[footer.sizeHint.width(),footer.sizeHint.height()],
                                  'minimum_hint':[footer.minimumSizeHint.width(),footer.minimumSizeHint.height()],
                                  'has_height_for_width':footer.hasHeightForWidth(),
                                  'height_for_current_width':footer.heightForWidth(footer.width),
                                  'layout_height_for_current_width':footer.layout().heightForWidth(footer.width),
                                  'instruction_hint':[widget.instruction.sizeHint.width(),widget.instruction.sizeHint.height()],
                                  'instruction_minimum_hint':[widget.instruction.minimumSizeHint.width(),widget.instruction.minimumSizeHint.height()],
                                  'instruction_height_for_current_width':widget.instruction.heightForWidth(widget.instruction.width)}
    entry['screenshot'] = name + '.png'
    window.grab().save(str(OUTPUT / entry['screenshot']))
    REPORT['layouts'].append(entry)
    (OUTPUT / ('layout-' + PHASE + '.json')).write_text(json.dumps(REPORT,indent=2)+'\n')


def points(widget, vertices):
    view = slicer.app.layoutManager().sliceWidget('Red')
    matrix=view.mrmlSliceNode().GetXYToRAS()
    inv=np.linalg.inv(np.array([[matrix.GetElement(r,c) for c in range(4)] for r in range(4)]))
    interactor=view.sliceView().interactorStyle().GetInteractor()
    for point in vertices:
        ras=widget.session.case.affine_ras @ [*point,1]
        xy=inv @ ras
        interactor.SetEventInformation(int(round(xy[0])),int(round(xy[1])),0,0)
        for event in ('EnterEvent','MouseMoveEvent','LeftButtonPressEvent','LeftButtonReleaseEvent'):
            interactor.InvokeEvent(event)
        events()


def discard(widget):
    seen=[]
    timer=qt.QTimer()
    deadline=time.monotonic()+3
    def accept():
        modal=qt.QApplication.activeModalWidget()
        if isinstance(modal,qt.QMessageBox):
            for button in modal.buttons():
                if str(button.text).replace('&','')=='Discard contour':
                    seen.append(True)
                    button.click()
        if time.monotonic()>deadline and modal is not None:
            modal.reject()
            timer.stop()
    timer.connect('timeout()',accept)
    timer.start(20)
    widget.discardContourButton.click()
    timer.stop()
    events()
    completed=bool(seen) and not widget._pendingDraw()
    check('actual Discard confirmation handled',completed)
    if not completed:
        raise AssertionError('Actual Discard confirmation did not complete.')


def run():
    global WIDGET
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for protected in (TEST_DIR.parent,):
        try:
            OUTPUT.relative_to(protected)
            raise ValueError('Synthetic outputs must remain outside the repository.')
        except ValueError as exc:
            if str(exc).startswith('Synthetic outputs'):
                raise
    try:
        source=OUTPUT/'Synthetic source'
        if PHASE=='layout':
            dataset,truth=make_draw_matrix(source)
        else:
            dataset=Dataset(source)
            truth=json.loads((source/'synthetic_truth.json').read_text())
        slicer.util.selectModule('MeniscusAnnotator')
        WIDGET=slicer.modules.meniscusannotator.widgetRepresentation().self()
        events(.3)
        widget=WIDGET
        check('isolated settings file matches test output',Path(str(widget.settings.fileName())).resolve()==(OUTPUT/'Workspace.ini').resolve())
        widget.openDataset(str(source),work_root=str(OUTPUT/'Work'))
        widget.openCase(dataset.cases[1].key)
        window=slicer.util.mainWindow()
        window.showNormal()
        events(.5)
        REPORT.update(module_source=inspect.getsourcefile(widget.__class__),
                      source_sha256=sha256(inspect.getsourcefile(widget.__class__)),
                      runtime=slicer.app.applicationVersion,revision=slicer.app.repositoryRevision,
                      platform=platform.platform(),machine=platform.machine(),
                      scaling_environment=os.environ.get('QT_SCALE_FACTOR'))
        if PHASE=='persist':
            check('fresh process restores Cases hidden',not widget.caseListDock.isVisible())
            check('fresh process restores Tools hidden',not widget.rightDock.isVisible())
            check('fresh process Cases toggle agrees',not widget.casesToggle.checked)
            check('fresh process Tools toggle agrees',not widget.toolsToggle.checked)
            check('fresh process restores Regions task',widget.annotationTask=='regions')
            check('fresh process collapsed instruction names task and target','Regions' in str(widget.instruction.text) and 'Medial body' in str(widget.instruction.text))
            capture(widget,'persist-collapsed-1280',1280,800)
            widget.closeCase()
        else:
            widget.casesToggle.setChecked(True);widget.toolsToggle.setChecked(True)
            widget.goSlice(truth[dataset.cases[1].key]['medial_seed_ijk'][2])
            check('case opens with Draw selected',widget.editor.activeEffect().name=='Draw' and widget.toolButtons['Draw'].checked)
            capture(widget,'whole-1280',1280,800)
            widget.taskCombo.setCurrentIndex(1)
            widget.regionCombo.setCurrentIndex(1)
            events()
            check('whole-only fixture begins with regions Not assigned','Not assigned' in str(widget.regionalProtocolLabel.text))
            REPORT['fonts']={key:font_details(control) for key,control in controls(widget).items() if isinstance(control,(qt.QPushButton,qt.QToolButton,qt.QLabel,qt.QComboBox,qt.QSpinBox))}
            for name in ('save','review','tool_Draw','tool_Erase','tool_Paint','undo','redo','task','region'):
                font=REPORT['fonts'][name]
                check('ordinary font '+name+' 11pt regular',font['resolved_pt']==11 and font['resolved_weight']==50,font)
            capture(widget,'regions-1280',1280,800)
            for width,height in ((1440,900),(1024,640)):
                capture(widget,'regions-'+str(width),width,height)
            widget.casesToggle.click();events()
            capture(widget,'focused-1280',1280,800)
            widget.toolsToggle.click();events()
            check('collapsed tools instruction identifies region/task/tool','Regions' in str(widget.instruction.text) and 'Medial body' in str(widget.instruction.text) and 'Draw' in str(widget.instruction.text))
            capture(widget,'collapsed-1280',1280,800)
            widget.toolsToggle.click();widget.casesToggle.click();events()
            for width,height in ((1280,800),(1024,640)):
                window.resize(width,height);events(.2)
                k=widget.currentSlice
                points(widget,[(23,25,k),(27,25,k),(27,29,k)])
                check('pending contour present at '+str(width),bool(widget._pendingDraw()))
                capture(widget,'pending-'+str(width),width,height,True)
                discard(widget)
            widget.regionalAssessmentPanel.collapsed=False
            widget.caseReviewPanel.collapsed=False
            widget.regionNotes.setFocus()
            capture(widget,'details-expanded-1280',1280,800)
            before_arrays=tuple(value.copy() for value in widget.collectArrays())
            for kind in (qt.QEvent.KeyPress,qt.QEvent.KeyRelease):
                qt.QApplication.sendEvent(widget.regionNotes,qt.QKeyEvent(kind,qt.Qt.Key_E,qt.Qt.NoModifier,'e'))
            events()
            check('typing regional notes does not select Erase',widget.editor.activeEffect().name=='Draw' and str(widget.regionNotes.toPlainText())=='e')
            for kind in (qt.QEvent.KeyPress,qt.QEvent.KeyRelease):
                qt.QApplication.sendEvent(widget.regionNotes,qt.QKeyEvent(kind,qt.Qt.Key_Z,qt.Qt.ControlModifier,'z'))
            events()
            check('notes Undo stays inside the text field',str(widget.regionNotes.toPlainText())=='' and widget.editor.activeEffect().name=='Draw' and all(np.array_equal(a,b) for a,b in zip(before_arrays,widget.collectArrays())))
            widget.regionalAssessmentPanel.collapsed=True
            widget.caseReviewPanel.collapsed=True
            widget.toolButtons['Paint'].click();events()
            check('Paint displays brush size',widget.brushRow.isVisible())
            capture(widget,'paint-1280',1280,800)
            widget.toolButtons['Draw'].click();events()
            check('Draw hides brush size',not widget.brushRow.isVisible())
            widget.saveButton.click();events()
            check('Save created checkpoint',widget.session.current_checkpoint is not None)
            widget.casesToggle.setChecked(False);widget.toolsToggle.setChecked(False)
            widget.settings.sync()
            widget.closeCase()
        REPORT['passed']=all(item['passed'] for item in REPORT['checks'])
    except Exception:
        REPORT['passed']=False
        REPORT['error']=traceback.format_exc()
        if WIDGET:
            REPORT['diagnostic']=WIDGET._diagnostic
            try:
                if WIDGET._pendingDraw():
                    WIDGET._pendingDraw().resetPolyData()
                WIDGET._loading=True;WIDGET.dirty=False;WIDGET.closeCase()
            except Exception:
                REPORT['cleanup_error']=traceback.format_exc()
    (OUTPUT/('layout-'+PHASE+'.json')).write_text(json.dumps(REPORT,indent=2)+'\n')
    print('MENISCUS_LAYOUT_RESULT',json.dumps({'passed':REPORT['passed'],'checks':len(REPORT['checks']),'report':str(OUTPUT/('layout-'+PHASE+'.json'))}),flush=True)
    slicer.app.exit(0 if REPORT['passed'] else 1)


if __name__=='__main__':
    run()
