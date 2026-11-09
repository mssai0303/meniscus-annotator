"""Focused native desktop regressions for the independent review repairs.

Run through SLICERRC, with MENISCUS_REPAIR_OUTPUT outside the application tree.
Qt/VTK events exercise visible controls and ordinary reader/job configuration;
this is not an OS-input, human, anatomical, or native Windows acceptance claim.
No _practiceConfig, direct openDataset, or direct export helper is used.
"""
import csv
import datetime
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import zipfile

import nibabel as nib
import numpy as np
import qt
import slicer
import vtk

TEST_DIR=Path(__file__).resolve().parent
sys.path.insert(0,str(TEST_DIR))
if (TEST_DIR.parent/'MeniscusAnnotatorLib').is_dir():
    sys.path.insert(0,str(TEST_DIR.parent))
from draw_fixture import make_draw_matrix
from MeniscusAnnotatorLib.core import Dataset,WorkStore,load_job_config,sha256
from MeniscusAnnotatorLib.regions import REGIONS

OUTPUT=Path(os.environ['MENISCUS_REPAIR_OUTPUT']).resolve()
PHASE=os.environ.get('MENISCUS_REPAIR_PHASE','workflow')
ACTOR='Software QA (ordinary workflow)'
REPORT={}
WIDGET=None


def events(seconds=.03):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        slicer.app.processEvents()
        time.sleep(.003)


def check(name,value,detail=None):
    item={'name':name,'passed':bool(value)}
    if detail is not None:
        item['detail']=detail
    REPORT['checks'].append(item)
    (OUTPUT/('repair-progress-'+PHASE+'.json')).write_text(json.dumps(item,indent=2)+'\n')
    if not value:
        raise AssertionError(name)


def click(control):
    check('target control available '+str(getattr(control,'objectName','')),
          control is not None and control.isVisible() and control.isEnabled())
    ancestor=control.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor,qt.QScrollArea):
            ancestor.ensureWidgetVisible(control)
            events()
            break
        ancestor=ancestor.parentWidget()
    check('clicked control fully visible '+str(getattr(control,'objectName','')),
          control.visibleRegion().boundingRect().contains(control.rect))
    control.setFocus(qt.Qt.MouseFocusReason)
    center=qt.QPointF(min(8.,control.width/2) if isinstance(control,(qt.QCheckBox,qt.QRadioButton)) else control.width/2,control.height/2)
    for kind,buttons in [(qt.QEvent.MouseButtonPress,qt.Qt.LeftButton),
                         (qt.QEvent.MouseButtonRelease,qt.Qt.NoButton)]:
        qt.QApplication.sendEvent(control,qt.QMouseEvent(kind,center,qt.Qt.LeftButton,buttons,qt.Qt.NoModifier))
    events()


def key(control,code,text='',modifiers=qt.Qt.NoModifier):
    control.setFocus()
    for kind in (qt.QEvent.KeyPress,qt.QEvent.KeyRelease):
        qt.QApplication.sendEvent(control,qt.QKeyEvent(kind,code,modifiers,text))
    events()


def by_text(parent,text):
    found=[w for w in parent.findChildren(qt.QAbstractButton)
           if str(w.text).replace('&','')==text and w.isVisible()]
    if len(found)!=1:
        raise AssertionError('Expected one visible button '+text)
    return found[0]


def action(button,prefix):
    menu=button.menu()
    check('workspace menu available',isinstance(menu,qt.QMenu))
    matches=[a for a in menu.actions() if str(a.text).startswith(prefix)]
    check('one actual QAction '+prefix,len(matches)==1)
    # Trigger the installed UI action; the resulting dialogs are interacted
    # with normally. OS-level menu clicks are a separate smoke-test scope.
    matches[0].trigger()
    events()


def modal_flow(callback,handler,timeout=30):
    timer=qt.QTimer()
    timer.setInterval(20)
    state={'error':None,'busy':[]}
    started=time.monotonic()
    def tick():
        modal=qt.QApplication.activeModalWidget()
        if time.monotonic()-started>timeout and state['error'] is None:
            visible=[{'name':str(w.objectName),'title':str(w.windowTitle)}
                     for w in qt.QApplication.topLevelWidgets() if w.isVisible()]
            state['error']='UI timeout: '+json.dumps({'modal':str(modal.windowTitle) if modal else None,
                'busy':[str(w.windowTitle) for w in state['busy']],'visible':visible})
        if state['error']:
            if modal is not None:
                modal.reject()
            return
        if modal is None or any(modal==item for item in state['busy']):
            return
        # Accepting one dialog can synchronously open a DIFFERENT nested dialog
        # inside the injected release event. Suppress only the same modal.
        state['busy'].append(modal)
        REPORT.setdefault('modal_events',[]).append({'event':'enter','name':str(modal.objectName),
            'title':str(modal.windowTitle),'seconds':time.monotonic()-started})
        try:
            handler(modal)
        except Exception:
            state['error']=traceback.format_exc()
            modal.reject()
        finally:
            state['busy']=[item for item in state['busy'] if item!=modal]
    timer.connect('timeout()',tick)
    timer.start()
    try:
        callback()
    finally:
        timer.stop()
    if state['error']:
        raise AssertionError(state['error'])
    events()


def folder(modal,path):
    check('ordinary Qt folder picker displayed',isinstance(modal,qt.QFileDialog))
    # Fill and accept the dialog's ordinary location input, not an app API.
    entry=modal.findChild(qt.QLineEdit,'fileNameEdit')
    if entry is None:
        raise AssertionError('Folder picker has no editable location control')
    entry.setText(str(path))
    keys=modal.findChild(qt.QDialogButtonBox)
    candidates=[b for b in keys.buttons() if b.isEnabled()
                and keys.buttonRole(b)==qt.QDialogButtonBox.AcceptRole]
    check('folder picker Select control available',len(candidates)==1)
    click(candidates[0])


def whole(widget):
    return tuple(a.copy() for a in widget.collectArrays())


def same(a,b):
    return all(np.array_equal(x,y) for x,y in zip(a,b))


def prepare():
    source=OUTPUT/'Synthetic ordinary reader inputs'
    _,truth=make_draw_matrix(source)
    # Ordinary draft protocol deliberately has no software-practice shortcut.
    job=json.loads((source/'correction_job.json').read_text())
    job.pop('practice_context',None)
    job.pop('annotator',None)
    job['protocol']={'version':'SYNTHETIC-ORDINARY-DRAFT-REPAIR-1','status':'draft'}
    (source/'correction_job.json').write_text(json.dumps(job,indent=2)+'\n')
    (OUTPUT/'source-hashes.json').write_text(json.dumps({p.relative_to(source).as_posix():sha256(p)
        for p in source.rglob('*') if p.is_file()},indent=2)+'\n')
    return source,truth


def attach():
    global WIDGET
    check('ordinary SLICERRC launch route',bool(os.environ.get('SLICERRC'))
          and '--python-script' not in list(slicer.app.arguments()))
    slicer.util.selectModule('MeniscusAnnotator')
    WIDGET=widget=slicer.modules.meniscusannotator.widgetRepresentation().self()
    check('no hidden software-practice launcher configuration',widget._practiceConfig is None)
    path=Path(inspect.getsourcefile(widget.__class__)).resolve()
    REPORT.update(application_source_path=str(path),application_source_sha256=sha256(path),
                  source_identity=getattr(inspect.getmodule(widget.__class__),'SOURCE_IDENTITY',{}))
    window=slicer.util.mainWindow()
    window.showNormal()
    window.resize(1280,800)
    window.raise_()
    window.activateWindow()
    events(.5)
    # Deterministic Qt-owned pickers for injected UI checks. A separate guarded
    # OS smoke covers the native macOS picker; this attribute is process-local.
    qt.QApplication.setAttribute(qt.Qt.AA_DontUseNativeDialogs,True)
    REPORT['picker_scope']='Qt-owned actual folder dialogs, process-local AA_DontUseNativeDialogs for injected events; OS native-picker smoke reported separately.'
    return widget


def open_dataset(widget,source,previous=False,existing_work=None):
    seen=[]
    def handle(modal):
        name=str(modal.objectName)
        title=str(modal.windowTitle)
        if isinstance(modal,qt.QFileDialog) and title=='Open dataset':
            seen.append('dataset_picker')
            folder(modal,source)
        elif name=='MeniscusReaderIdentityDialog':
            entry=modal.findChild(qt.QLineEdit,'MeniscusReaderIdentityInput')
            proceed=modal.findChild(qt.QPushButton,'MeniscusReaderIdentityContinue')
            confirmed=modal.findChild(qt.QCheckBox,'MeniscusReaderIdentityConfirmed')
            if previous:
                check('remembered reader requires deliberate confirmation',confirmed is not None
                      and not confirmed.checked and not proceed.enabled)
            entry.setText(ACTOR)
            if confirmed is not None:
                click(confirmed)
            click(proceed)
            seen.append('reader')
        elif name=='MeniscusReaderConfirmDialog':
            check('assigned Software QA identity requires deliberate confirmation',ACTOR in str(modal.text))
            click(modal.button(qt.QMessageBox.Yes))
            seen.append('assigned_reader')
        elif title=='Local work folder':
            path=str(modal.informativeText)
            check('default work proposal is local application data',
                  'documents' not in path.lower()
                  and not any(s in path.lower() for s in ('onedrive','dropbox','cloudstorage','icloud','google drive')))
            REPORT['proposed_work_folder']=path
            click(by_text(modal,'Open existing work' if existing_work else 'Change location'))
            seen.append('work_proposal')
        elif isinstance(modal,qt.QFileDialog) and title=='Open existing work folder':
            check('legacy work selection is deliberate',existing_work is not None)
            folder(modal,existing_work)
        elif isinstance(modal,qt.QFileDialog) and title=='Choose local work folder':
            target=OUTPUT/'Local ordinary reader work'
            target.mkdir(exist_ok=True)
            folder(modal,target)
        else:
            raise AssertionError('Unexpected ordinary setup dialog: '+title+' / '+name)
    modal_flow(lambda:action(widget.datasetMenuButton,'Open dataset'),handle)
    check('ordinary reader dataset opened through visible controls',widget.dataset is not None
          and Path(widget.dataset.root)==source.resolve() and widget.store.annotator==ACTOR)
    check('ordinary reader job has draft protocol without hidden practice context',
          widget.store.practice_context is None and widget.store.job['protocol']['status']=='draft')
    REPORT['setup_dialogs']=seen
    REPORT['work_folder']=str(widget.store.root)


def open_case(widget,key_value):
    rows=[r for r in range(widget.caseTable.rowCount)
          if widget.caseTable.item(r,0).data(qt.Qt.UserRole)==key_value]
    check('requested synthetic case listed',len(rows)==1)
    widget.caseTable.setCurrentCell(rows[0],0)
    widget.caseTable.selectRow(rows[0])
    click(widget.openCaseButton)
    check('case opened from actual case list',widget.session is not None and widget.session.case.key==key_value)
    REPORT['resolved_fonts']={}
    for name,control in [('identity',widget.identityLabel),('save_state',widget.saveStatus),
                         ('ordinary_button',widget.saveButton),('draw',widget.toolButtons['Draw']),
                         ('erase',widget.toolButtons['Erase']),('instruction',widget.instruction)]:
        control.ensurePolished()
        font=control.font
        info=qt.QFontInfo(font)
        REPORT['resolved_fonts'][name]={'requested_family':font.family(),'requested_pt':font.pointSizeF(),
            'requested_weight':font.weight(),'resolved_family':info.family(),'resolved_pt':info.pointSizeF(),
            'resolved_weight':info.weight(),'resolved_bold':info.bold(),'exact_match':info.exactMatch()}



def save(widget):
    before=widget.session.current_checkpoint
    click(widget.saveButton)
    check('Save draft completes without losing the current case',widget.session.current_checkpoint is not None
          and not widget.dirty and 'Saved' in str(widget.saveStatus.text))
    return widget.session.current_checkpoint


def approve(widget):
    if widget.goApprovalButton.isVisible():
        click(widget.goApprovalButton)
    else:
        widget.caseReviewPanel.collapsed=False
        events()
    for control in (widget.medialConsidered,widget.lateralConsidered):
        if not control.checked:
            click(control)
    scroll=widget.rightDock.findChild(qt.QScrollArea)
    scroll.ensureWidgetVisible(widget.approveButton)
    events()
    seen=[]
    def handle(modal):
        check('deliberate practice approval dialog',str(modal.windowTitle)=='Approve case'
              and ACTOR in str(modal.text))
        seen.append(True)
        click(modal.button(qt.QMessageBox.Yes))
    modal_flow(lambda:click(widget.approveButton),handle)
    check('whole case practice-approved by explicit Software QA identity',bool(seen)
          and widget.session.state['status']=='practice_approved'
          and widget.session.state['annotator']==ACTOR)
    widget.caseReviewPanel.collapsed=True
    events()


def review_all(widget):
    for k in range(widget.session.case.n_slices):
        widget.sliceSlider.setValue(k+1)
        events()
        if not widget.session.state['review'][k]['reviewed']:
            click(widget.reviewButton)


def export(widget,cancel=False,selected=False,earlier=False,require_newer=False):
    seen=[]
    target=OUTPUT/'Exports'
    target.mkdir(exist_ok=True)
    existing=set(target.rglob('*.zip'))
    def handle(modal):
        name,title=str(modal.objectName),str(modal.windowTitle)
        if name=='MeniscusExportDialog':
            practice=modal.findChild(qt.QCheckBox,'MeniscusExportPractice')
            check('B1 ordinary draft protocol defaults to explicit practice export',
                  practice is not None and practice.checked and not practice.enabled)
            only=modal.findChild(qt.QCheckBox,'MeniscusExportSelectedOnly')
            if bool(only.checked)!=selected:
                click(only)
            check('selected-only choice actually applied',bool(only.checked)==selected)
            summary=modal.findChild(qt.QTableWidget,'MeniscusExportSummary')
            check('export preflight explicitly lists version and omissions',summary is not None and summary.rowCount>0)
            earlier_box=modal.findChild(qt.QCheckBox,'MeniscusExportEarlier')
            def snapshot(stage):
                confirm=modal.findChild(qt.QPushButton,'MeniscusExportConfirm')
                message=modal.findChild(qt.QLabel,'MeniscusExportSummaryText')
                record={'stage':stage,'selected_only':bool(only.checked),
                    'earlier_checked':bool(earlier_box.checked),'earlier_width':earlier_box.width,
                    'earlier_text_width':qt.QFontMetrics(earlier_box.font).horizontalAdvance(str(earlier_box.text)),
                    'export_enabled':confirm.enabled,'message':str(message.text),
                    'rows':[[str(summary.item(r,c).text()) if summary.item(r,c) else ''
                             for c in range(summary.columnCount)] for r in range(summary.rowCount)]}
                records=REPORT.setdefault('export_preflight_events',[])
                records.append(record)
                modal.grab().save(str(OUTPUT/('repair-export-preflight-'+str(len(records))+'.png')))
            snapshot('initial')

            if require_newer:
                summary_text=' '.join(str(summary.item(r,c).text()) for r in range(summary.rowCount)
                    for c in range(summary.columnCount) if summary.item(r,c) is not None).lower()
                check('I3 newer unapproved work is explicit in Export preflight',
                      'newer' in summary_text and earlier_box is not None and not earlier_box.checked)
                if not earlier:
                    check('default export cannot silently include old approval',
                          not modal.findChild(qt.QPushButton,'MeniscusExportConfirm').enabled)
            if earlier:
                check('older version export requires deliberate opt-in',earlier_box is not None and not earlier_box.checked)
                click(earlier_box)
                snapshot('explicit_earlier_clicked')
                check('explicit earlier-version choice actually applied',earlier_box.checked)
            seen.append('preflight')
            if cancel:
                click(modal.findChild(qt.QPushButton,'MeniscusExportCancel'))
            else:
                click(modal.findChild(qt.QPushButton,'MeniscusExportConfirm'))
        elif isinstance(modal,qt.QFileDialog) and title in ('Export results to folder','Export return ZIP to folder'):
            folder(modal,target)
        elif title=='Export complete':
            seen.append('complete')
            click(modal.button(qt.QMessageBox.Close))
        else:
            raise AssertionError('Unexpected Export dialog: '+title+' / '+name)
    modal_flow(lambda:action(widget.datasetMenuButton,'Export results'),handle)
    created=set(target.rglob('*.zip'))-existing
    if cancel:
        check('Cancel export creates no ZIP and preserves work',not created and 'preflight' in seen)
        return None
    check('ordinary default Export creates one versioned ZIP',len(created)==1 and 'complete' in seen)
    return created.pop()


def verify_zip(path,expected,earlier=False):
    with zipfile.ZipFile(path) as archive:
        receipt=json.loads(archive.read('results.json'))
        check('practice ZIP explicitly non-research',receipt.get('practice_only') is True)
        check('export receipt includes a reviewed plan',receipt.get('export_plan') is not None)
        record=receipt['cases'][0]
        case=WIDGET.session.case
        for name,array in [('labels.nii.gz',expected[0]),('uncertainty.nii.gz',expected[1])]:
            extracted=OUTPUT/('verify-'+path.stem+'-'+name)
            extracted.write_bytes(archive.read(record['folder']+'/'+name))
            image=nib.load(str(extracted))
            check('full-grid exact values and geometry '+name,
                  np.array_equal(np.asarray(image.dataobj).transpose(2,1,0),array)
                  and image.shape==case.shape_xyz and np.allclose(image.affine,case.affine_ras,atol=1e-4))
            check('practice NIfTI remains identifiable outside ZIP '+name,
                  b'PRACTICE' in image.header['descrip'].tobytes().upper())
        state=json.loads(archive.read(record['folder']+'/annotation.json'))
        check('ordinary practice annotation has explicit purpose and no research eligibility',
              state.get('annotation_purpose')=='protocol_practice'
              and state.get('research_eligible') is False and state.get('accepted_research_annotation') is False)
        eligibility=OUTPUT/('verify-'+path.stem+'-eligibility.nii.gz')
        eligibility.write_bytes(archive.read(record['folder']+'/research_eligibility.nii.gz'))
        check('practice export has separate zero research eligibility',
              not np.asarray(nib.load(str(eligibility)).dataobj).any())
        check('export selection identifies exact chosen version',
              record.get('export_selection',{}).get('selection')==('explicit_earlier_approval' if earlier else 'latest_approved'))


def erase_native(widget,point):
    click(widget.labelButtons['medial'])
    click(widget.toolButtons['Erase'])
    widget.brushSize.setValue(1.2)
    widget.sliceSlider.setValue(point[2]+1)
    events()
    view=slicer.app.layoutManager().sliceWidget('Red')
    xy=view.mrmlSliceNode().GetXYToRAS()
    transform=np.array([[xy.GetElement(r,c) for c in range(4)] for r in range(4)])
    screen=np.linalg.inv(transform)@(widget.session.case.affine_ras@[*point,1])
    native=view.sliceView().interactorStyle().GetInteractor()
    native.SetEventInformation(int(round(screen[0])),int(round(screen[1])),0,0)
    for name in ('EnterEvent','MouseMoveEvent','LeftButtonPressEvent','LeftButtonReleaseEvent'):
        native.InvokeEvent(name)
    events(.1)


def configure(output,actor=ACTOR,report=None,phase=None):
    """Reuse only generic visible-control helpers from an isolated maintainer RC."""
    global OUTPUT,ACTOR,REPORT,PHASE
    OUTPUT=Path(output).resolve()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    ACTOR=actor
    if report is not None:
        REPORT=report
    if phase is not None:
        PHASE=phase


def smoke():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    open_case(widget,next(iter(truth)))
    check('first visible practice image opens at a masked acquired slice',whole(widget)[0][widget.currentSlice].any())
    slicer.app.layoutManager().sliceWidget('Red').sliceView().forceRender()
    slicer.util.mainWindow().grab().save(str(OUTPUT/'repair-first-workspace.png'))
    REPORT['ui_refs']={name:bool(hasattr(widget,name)) for name in
        ('taskButtons','regionButtons','assessmentButtons','goApprovalButton','stepBar')}
    widget.closeCase()


def workflow():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    key_value=next(iter(truth))
    open_case(widget,key_value)
    labels=whole(widget)[0]
    widget.notes.setPlainText('AUTOMATED SOFTWARE QA using injected desktop events; not human anatomical review.')
    check('new correction case opens on a meaningful masked slice',labels[widget.currentSlice].any())
    save(widget)
    before_versions=len(list((widget.session.folder/'versions').glob('*')))
    elapsed=[]
    for k in range(min(5,widget.session.case.n_slices)):
        widget.sliceSlider.setValue(k+1)
        events()
        started=time.monotonic()
        click(widget.reviewButton)
        elapsed.append(time.monotonic()-started)
    after_versions=len(list((widget.session.folder/'versions').glob('*')))
    REPORT['review_click_seconds']=elapsed
    check('review uses lightweight durable records, not full image checkpoints',
          before_versions==after_versions and bool(list((widget.session.folder/'review_journal').rglob('r-*.json'))))
    check('synthetic review avoids former second-long checkpoint stall',max(elapsed)<1.,elapsed)
    review_all(widget)
    check('finished review provides next-step approval guidance',
          hasattr(widget,'goApprovalButton') and widget.goApprovalButton.isVisible()
          and 'approv' in str(widget.instruction.text).lower())
    approve(widget)
    approved=whole(widget)
    approved_path=widget.session.current_checkpoint
    status=widget.session.state['status']
    click(widget.reviewButton)
    check('I3 repeated review is idempotent after approval',widget.session.state['status']==status
          and widget.session.current_checkpoint==approved_path and widget.session.state['approval'] is not None)
    export(widget,cancel=True,selected=True)
    first=export(widget,selected=True)
    verify_zip(first,approved)
    erase_native(widget,truth[key_value]['medial_seed_ijk'])
    current=whole(widget)
    check('actual Erase creates a newer draft without modifying the approved arrays',
          not same(current,approved) and widget.session.state['approval'] is None)
    save(widget)
    export(widget,cancel=True,selected=True,require_newer=True)
    explicit=export(widget,selected=True,earlier=True,require_newer=True)
    verify_zip(explicit,approved,earlier=True)
    check('exporting explicit earlier approval does not hide current draft',
          same(whole(widget),current) and widget.session.state['status']!='practice_approved')
    review_all(widget)
    approve(widget)
    latest=export(widget,selected=True)
    verify_zip(latest,current)
    # Region assessments are metadata, not an edit to the reviewed masks.
    click(widget.taskButtons['regions'])
    click(widget.labelButtons['medial'])
    click(widget.regionButtons['anterior'])
    widget.sliceSlider.setValue(1)
    events()
    for _ in range(3):
        click(widget.reviewButton)
    before=json.loads(json.dumps(widget.regionalState['review']))
    widget.regionalAssessmentPanel.collapsed=False
    events()
    click(widget.assessmentButtons['present'])
    check('I2 regional assessment preserves all explicit slice review marks',widget.regionalState['review']==before)
    check('assessment names its exact compartment and region',
          'Medial' in str(widget.regionalAssessmentPanel.text)
          and any(s in str(widget.regionalAssessmentPanel.text) for s in ('Anterior','anterior','AH')))
    click(widget.taskButtons['whole'])
    # Window-wide shortcuts must work after a panel click, without a view click.
    click(widget.toolButtons['Erase'])
    focused=qt.QApplication.focusWidget()
    old_k=widget.currentSlice
    if old_k==widget.session.case.n_slices-1:
        key(focused,qt.Qt.Key_Left)
        expected_k=old_k-1
    else:
        key(focused,qt.Qt.Key_Right)
        expected_k=old_k+1
    check('I4 navigation shortcut works after panel control focus',widget.currentSlice==expected_k)
    widget.notesPanel.collapsed=False
    events()
    widget.notes.setPlainText('')
    current=(widget.currentSlice,widget.activeLabel,widget.editor.activeEffect().name)
    for char in 'dep123rufa':
        key(widget.notes,ord(char.upper()),char)
    check('shortcuts remain inactive while typing notes',str(widget.notes.toPlainText())=='dep123rufa'
          and current==(widget.currentSlice,widget.activeLabel,widget.editor.activeEffect().name))
    widget.notes.setPlainText('AUTOMATED SOFTWARE QA using injected desktop events; not human anatomical review.')
    widget.sliceSlider.setValue(1) # remembered empty slices must remain accessible on resume
    events()
    save(widget)
    (OUTPUT/'expected-workflow.json').write_text(json.dumps({'case_key':key_value,'work':str(widget.store.root),
        'slice':widget.currentSlice,'review':widget.session.state['review'],'regional_review':widget.regionalState['review']},indent=2)+'\n')
    np.savez_compressed(OUTPUT/'expected-arrays.npz',labels=whole(widget)[0],uncertainty=whole(widget)[1])
    slicer.util.mainWindow().grab().save(str(OUTPUT/'repair-workflow.png'))
    check('original synthetic package remains byte-for-byte unchanged',
          json.loads((OUTPUT/'source-hashes.json').read_text())=={p.relative_to(source).as_posix():sha256(p)
            for p in source.rglob('*') if p.is_file()})
    widget.closeCase()


def resume():
    widget=attach()
    source=OUTPUT/'Synthetic ordinary reader inputs'
    open_dataset(widget,source,previous=True)
    expected=json.loads((OUTPUT/'expected-workflow.json').read_text())
    open_case(widget,expected['case_key'])
    values=np.load(OUTPUT/'expected-arrays.npz')
    check('cold restart preserves whole annotation and review',
          same(whole(widget),(values['labels'],values['uncertainty']))
          and widget.session.state['review']==expected['review'])
    check('cold restart preserves regional review and remembered slice',
          widget.regionalState['review']==expected['regional_review'] and widget.currentSlice==expected['slice'])
    widget.closeCase()


def journal_write():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    case_key=next(iter(truth))
    open_case(widget,case_key)
    save(widget)
    checkpoint=widget.session.current_checkpoint
    hashes={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()}
    for k in range(3):
        widget.sliceSlider.setValue(k+1)
        events()
        click(widget.reviewButton)
    click(widget.taskButtons['regions'])
    click(widget.labelButtons['medial'])
    for k in range(2):
        widget.sliceSlider.setValue(k+1)
        events()
        click(widget.reviewButton)
    check('metadata review leaves immutable full checkpoint untouched',
          widget.session.current_checkpoint==checkpoint
          and hashes=={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()})
    journals=list((widget.session.folder/'review_journal'/checkpoint.name).glob('r-*.json'))
    check('review was durably journaled before abrupt exit',bool(journals))
    expected={'case_key':case_key,'review':widget.session.state['review'],
              'regional_review':widget.regionalState['review'],'checkpoint':str(checkpoint),
              'checkpoint_hashes':hashes,'slice':widget.currentSlice}
    (OUTPUT/'expected-journal.json').write_text(json.dumps(expected,indent=2)+'\n')
    REPORT['simulated_crash']='Own synthetic process os._exit after durable journal; no close/save hook; no other PID touched.'


def journal_resume():
    widget=attach()
    source=OUTPUT/'Synthetic ordinary reader inputs'
    open_dataset(widget,source,previous=True)
    expected=json.loads((OUTPUT/'expected-journal.json').read_text())
    open_case(widget,expected['case_key'])
    check('abrupt-exit restart recovers exact whole and regional explicit reviews',
          widget.session.state['review']==expected['review']
          and widget.regionalState['review']==expected['regional_review'])
    check('journal recovery is identified and bound to exact saved checkpoint',
          widget.session.review_journal_pending
          and str(widget.session.current_checkpoint)==expected['checkpoint'])
    checkpoint=Path(expected['checkpoint'])
    check('crash recovery did not rewrite historical image checkpoint',
          expected['checkpoint_hashes']=={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()})
    save(widget)
    check('explicit Save merges recovered metadata into a new immutable version',
          widget.session.current_checkpoint!=checkpoint and not widget.session.review_journal_pending)
    widget.closeCase()


def legacy():
    source,truth=prepare()
    regional_fixture=PHASE=='legacy-regions'
    dataset=Dataset(source)
    job=load_job_config(source/'correction_job.json',dataset)
    work=OUTPUT/'Legacy named-reader work'
    store=WorkStore(work,dataset,job,reader=ACTOR)
    case=dataset.cases[0]
    volume=slicer.util.loadVolume(str(case.folder/'image.nii.gz'))
    node=slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode','SYNTHETIC legacy fixture')
    node.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    with store.open_case(case) as session:
        labels,uncertainty,_=session.load()
        for name,array in [('medial',labels==1),('lateral',labels==2),('uncertain',uncertainty!=0)]:
            node.GetSegmentation().AddEmptySegment(name,name)
            slicer.util.updateSegmentBinaryLabelmapFromArray(array.astype(np.uint8),node,name,volume)
        legacy_regions=legacy_uncertain=regional_state=None
        if regional_fixture:
            legacy_regions,legacy_uncertain,regional_state=session.load_regions()
            legacy_regions[tuple(reversed(truth[case.key]['medial_seed_ijk']))]=1
            for item in REGIONS:
                node.GetSegmentation().AddEmptySegment(item['id'],item['name'])
                slicer.util.updateSegmentBinaryLabelmapFromArray((legacy_regions==item['value']).astype(np.uint8),node,item['id'],volume)
            node.GetSegmentation().AddEmptySegment('regional_uncertain','Regional boundary uncertain')
            slicer.util.updateSegmentBinaryLabelmapFromArray(legacy_uncertain,node,'regional_uncertain',volume)
        def writer(path):
            storage=node.CreateDefaultStorageNode()
            slicer.mrmlScene.AddNode(storage)
            node.SetAndObserveStorageNodeID(storage.GetID())
            storage.SetCropToMinimumExtent(False)
            if not slicer.util.saveNode(node,str(path)):
                raise OSError('Synthetic legacy native segmentation write failed')
        old=session.save(labels,uncertainty,writer,**({'regions':legacy_regions,
            'regional_uncertainty':legacy_uncertain,'regional_state':regional_state} if regional_fixture else {}))
    # Construct the documented old six-payload schema; do not execute an old
    # hard-coded clinical reader or pretend a historical binary was tested.
    state=json.loads((old/'annotation.json').read_text())
    state['app_version']='0.1.0'
    state['annotation_purpose']='research_annotation'
    for field in ('reader_assignment','approval_purpose','research_eligible','accepted_research_annotation'):
        state.pop(field,None)
    (old/'annotation.json').write_text(json.dumps(state,indent=2)+'\n')
    if regional_fixture:
        previous_region_state=json.loads((old/'regions.json').read_text())
        previous_region_state['app_version']='0.1.0'
        previous_region_state.pop('reader_assignment',None)
        (old/'regions.json').write_text(json.dumps(previous_region_state,indent=2)+'\n')
    for name in (['labels.nii.gz','uncertainty.nii.gz','validity.nii.gz']+
                 (['regions.nii.gz','regional_uncertainty.nii.gz','regional_validity.nii.gz'] if regional_fixture else [])):
        image=nib.load(str(old/name))
        image.header['descrip']=b''
        image.header['intent_name']=b''
        nib.save(image,str(old/name))
    manifest=json.loads((old/'manifest.json').read_text())
    manifest.pop('research_eligibility',None)
    manifest['files_sha256'].pop('research_eligibility.nii.gz',None)
    (old/'research_eligibility.nii.gz').unlink()
    manifest['files_sha256']={name:sha256(old/name) for name in manifest['files_sha256']}
    (old/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    store.reader_assignment_path.unlink()
    before={p.name:sha256(p) for p in old.iterdir() if p.is_file()}
    check('legacy P1 fixture is named-reader six-file schema without binding',
          len(manifest['files_sha256'])==(11 if regional_fixture else 6) and 'reader_assignment' not in state and state['annotator']==ACTOR)
    for current in (node,volume):
        helpers=[current.GetDisplayNode(),current.GetStorageNode()]
        slicer.mrmlScene.RemoveNode(current)
        for helper in helpers:
            if helper:
                slicer.mrmlScene.RemoveNode(helper)
    widget=attach()
    open_dataset(widget,source,existing_work=work)
    open_case(widget,case.key)
    check('old named-reader annotation opens with exact masks and actor',
          same(whole(widget),(labels,uncertainty)) and widget.session.state['annotator']==ACTOR)
    if regional_fixture:
        check('legacy regional assignments reopen without inference or loss',same(widget.collectRegionalArrays(),(legacy_regions,legacy_uncertain)))
    new=save(widget)
    check('P1 first ordinary visible Save succeeds with matching regional reader binding',
          new!=old and widget.regionalState['reader_assignment']==widget.session.state['reader_assignment']
          and widget.session.state['annotator']==ACTOR)
    check('legacy original checkpoint remains byte-for-byte unchanged',
          before=={p.name:sha256(p) for p in old.iterdir() if p.is_file()})
    widget.closeCase()
    open_case(widget,case.key)
    check('migrated checkpoint reopens exact full-grid labels',same(whole(widget),(labels,uncertainty)))
    widget.closeCase()


def _matrix(value):
    return np.array([[value.GetElement(r,c) for c in range(4)] for r in range(4)])


def orientation():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    for case_key,item in truth.items():
        open_case(widget,case_key)
        case=widget.session.case
        view=slicer.app.layoutManager().sliceWidget('Red')
        frame=_matrix(view.mrmlSliceNode().GetSliceToRAS())[:3,:3]
        source_normal=case.affine_ras[:3,2]/np.linalg.norm(case.affine_ras[:3,2])
        source_up=case.affine_ras[:3,1]/np.linalg.norm(case.affine_ras[:3,1])
        if source_up[2]<0:
            source_up=-source_up
        check(case_key+' anterior-left superior-up proper frame on acquired planes',
              np.allclose(frame.T@frame,np.eye(3),atol=1e-5) and np.linalg.det(frame)>.999
              and -frame[1,0]>0 and frame[2,1]>0
              and abs(np.dot(frame[:,2],source_normal))>.999 and np.dot(frame[:,1],source_up)>.999)
        image=nib.load(str(case.folder/'image.nii.gz'))
        check(case_key+' source voxel grid unchanged by display orientation',
              np.array_equal(slicer.util.arrayFromVolume(widget.volume),np.asarray(image.dataobj).transpose(2,1,0)))
        masks=whole(widget)
        check(case_key+' meaningful first open is a masked acquired slice',masks[0][widget.currentSlice].any())
        expected='medial' if (case.affine_ras[0,2]>0)==(item['side']=='L') else 'lateral'
        check(case_key+' next-slice anatomical cue follows sourceK physical direction plus knee side',
              ('next → '+expected) in str(widget.sliceReadout.text).lower())
        for role,value in [('medial',1),('lateral',2)]:
            point=item[role+'_seed_ijk']
            check(case_key+' fixed '+role+' identity at original physical point',
                  masks[0][tuple(reversed(point))]==value
                  and np.allclose((case.affine_ras@[*point,1])[:3],item[role+'_seed_ras_mm'],atol=1e-4))
        if item['side']=='R':
            check(case_key+' unexpected relative label position is advisory, never relabeled or blocked',
                  widget._plausibility['status']=='check' and widget.plausibilityButton.isVisible()
                  and widget.saveButton.enabled)
        for index in (0,case.n_slices-1):
            widget.sliceSlider.setValue(index+1)
            events()
            actual_k=(np.linalg.inv(case.affine_ras)@_matrix(view.mrmlSliceNode().GetSliceToRAS())[:,3])[2]
            check(case_key+' complete acquired endpoint '+str(index),
                  widget.currentSlice==index and abs(actual_k-index)<.001)
        check(case_key+' navigation and advisory leave labels unchanged',same(whole(widget),masks))
    source_hashes=json.loads((OUTPUT/'source-hashes.json').read_text())
    check('orientation/advisory workflow leaves every source file unchanged',source_hashes=={
        p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()})
    slicer.util.mainWindow().grab().save(str(OUTPUT/'repair-orientation.png'))
    widget.closeCase()


def _bounds(control,window):
    rect=qt.QRect(control.mapTo(window,qt.QPoint(0,0)),control.size)
    bad=[]
    owner=control.parentWidget()
    while owner is not None and owner!=window:
        local=qt.QRect(control.mapTo(owner,qt.QPoint(0,0)),control.size)
        if not owner.rect.contains(local):
            bad.append(str(owner.objectName) or type(owner).__name__)
        owner=owner.parentWidget()
    return {'visible':control.isVisible(),'enabled':control.enabled,'window_rect':[rect.x(),rect.y(),rect.width(),rect.height()],
            'in_window':window.rect.contains(rect),'full_visible_region':control.visibleRegion().boundingRect().contains(control.rect),
            'clipped_ancestors':bad}


def _pending_points(widget,vertices):
    click(widget.toolButtons['Draw'])
    view=slicer.app.layoutManager().sliceWidget('Red')
    for point in vertices:
        screen=np.linalg.inv(_matrix(view.mrmlSliceNode().GetXYToRAS()))@(widget.session.case.affine_ras@[*point,1])
        native=view.sliceView().interactorStyle().GetInteractor()
        native.SetEventInformation(int(round(screen[0])),int(round(screen[1])),0,0)
        for name in ('EnterEvent','MouseMoveEvent','LeftButtonPressEvent','LeftButtonReleaseEvent'):
            native.InvokeEvent(name)
        events()


def _discard(widget):
    def handle(modal):
        check('explicit discard dialog has safe Keep drawing default',
              str(modal.objectName)=='MeniscusDiscardContourDialog'
              and str(modal.defaultButton().text).replace('&','')=='Keep drawing')
        choices=[b for b in modal.buttons() if str(b.text).replace('&','') in ('Discard','Discard contour')]
        check('explicit discard control present',len(choices)==1)
        click(choices[0])
    modal_flow(lambda:click(widget.discardContourButton),handle)


def layout():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    open_case(widget,next(iter(truth)))
    window=slicer.util.mainWindow()
    expected_dpr=float(os.environ.get('MENISCUS_REPAIR_EXPECT_DPR',window.devicePixelRatioF()))
    REPORT['qt_scaling']={'factor_environment':os.environ.get('QT_SCALE_FACTOR'),
        'rounding_environment':os.environ.get('QT_SCALE_FACTOR_ROUNDING_POLICY'),
        'expected_dpr':expected_dpr,'actual_dpr':window.devicePixelRatioF(),
        'rounding_policy':int(qt.QGuiApplication.highDpiScaleFactorRoundingPolicy()),
        'scope':'Actual Qt scale-factor simulation on Mac; not native Windows per-monitor DPI or OS-setting acceptance.'}
    check('actual Qt uses requested fractional DPR without integer rounding',abs(window.devicePixelRatioF()-expected_dpr)<.01)
    check('pre-application PassThrough rounding policy active',REPORT['qt_scaling']['rounding_policy']==5)
    REPORT['layouts']=[]
    for mode in ('whole','regions'):
        click(widget.taskButtons[mode])
        for width,height in [(1280,800),(1440,900),(960,540),(960,480),(800,480)]:
            window.resize(width,height)
            events(.2)
            view=slicer.app.layoutManager().sliceWidget('Red').sliceView()
            view.forceRender()
            controls={'identity':widget.identityLabel,'save_state':widget.saveStatus,'readout':widget.sliceReadout,
                'slider':widget.sliceSlider,'previous':widget.previousButton,'next':widget.nextButton,
                'review':widget.reviewButton,'save':widget.saveButton,'instruction':widget.instruction,
                'undo':widget.undoButton,'redo':widget.redoButton,
                **{'task_'+key:value for key,value in widget.taskButtons.items()},
                **{'tool_'+key:value for key,value in widget.toolButtons.items()},
                'medial':widget.labelButtons['medial'],'lateral':widget.labelButtons['lateral']}
            if mode=='regions':
                controls.update({'region_'+key:value for key,value in widget.regionButtons.items()})
            else:
                controls['uncertain']=widget.labelButtons['uncertain']
            entry={'mode':mode,'requested_size':[width,height],'actual_size':[window.width,window.height],
                'dpr':window.devicePixelRatioF(),'canvas':[view.width,view.height],
                'header_height':widget.topBar.height,'step_height':widget.stepBar.height,'footer_height':widget.bottomBar.height,
                'minimum_hint':[window.minimumSizeHint.width(),window.minimumSizeHint.height()],
                'controls':{}}
            REPORT['layouts'].append(entry)
            check(mode+' requested small client geometry supported '+str((width,height)),window.width==width and window.height==height)
            for name,control in controls.items():
                detail=_bounds(control,window)
                entry['controls'][name]=detail
                check(mode+' control visible '+name+' '+str((width,height)),
                      detail['visible'] and detail['in_window'] and detail['full_visible_region'] and not detail['clipped_ancestors'],detail)
            horizontal=[bar for bar in window.findChildren(qt.QScrollBar) if bar.isVisible() and bar.orientation==qt.Qt.Horizontal and bar.maximum>0]
            check(mode+' no horizontal panel scrolling '+str((width,height)),not horizontal)
            window.grab().save(str(OUTPUT/('repair-layout-'+mode+'-'+str(width)+'x'+str(height)+'.png')))
            if (width,height)==(960,540):
                k=widget.currentSlice
                before=whole(widget)
                _pending_points(widget,[(43,33,k),(53,33,k),(48,43,k)])
                events(.2)
                for name,control in [('finish',widget.finishContourButton),('discard',widget.discardContourButton),
                                     ('instruction',widget.instruction),('save',widget.saveButton),('review',widget.reviewButton)]:
                    detail=_bounds(control,window)
                    check(mode+' pending contour accessible '+name,detail['visible'] and detail['in_window']
                          and detail['full_visible_region'] and not detail['clipped_ancestors'],detail)
                window.grab().save(str(OUTPUT/('repair-pending-'+mode+'.png')))
                _discard(widget)
                check(mode+' layout contour discard never alters committed anatomy',same(whole(widget),before))
    widget.closeCase()


def guide():
    source,truth=prepare()
    widget=attach()
    open_dataset(widget,source)
    case_key=next(iter(truth))
    open_case(widget,case_key)
    window=slicer.util.mainWindow()
    window.resize(1280,800)
    events(.15)
    view=slicer.app.layoutManager().sliceWidget('Red')
    view.sliceView().forceRender()
    window.grab().save(str(OUTPUT/'repair-guide-whole.png'))
    point=truth[case_key]['medial_seed_ijk']
    widget.sliceSlider.setValue(point[2]+1)
    events()
    x,y,k=point
    _pending_points(widget,[(x-2,y-2,k),(x+2,y-2,k),(x,y+2,k)])
    events(.15)
    view.sliceView().forceRender()
    window.grab().save(str(OUTPUT/'repair-guide-unfinished.png'))
    _discard(widget)
    click(widget.taskButtons['regions'])
    click(widget.regionButtons['anterior'])
    _pending_points(widget,[(x-2,y-2,k),(x+2,y-2,k),(x+2,y+2,k),(x-2,y+2,k)])
    native=view.sliceView().interactorStyle().GetInteractor()
    native.InvokeEvent('RightButtonPressEvent')
    native.InvokeEvent('RightButtonReleaseEvent')
    events(.15)
    check('guide captures manually assigned native regional draft',np.any(widget.collectRegionalArrays()[0]==1))
    widget.regionalAssessmentPanel.collapsed=True
    widget.notesPanel.collapsed=True
    events()
    view.sliceView().forceRender()
    window.grab().save(str(OUTPUT/'repair-guide-regions.png'))
    widget.closeCase()


def run_phase(exit_application=True):
    global REPORT
    try:
        OUTPUT.relative_to(TEST_DIR.parent)
    except ValueError:
        pass
    else:
        raise ValueError('Synthetic repair outputs must remain outside the source tree.')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    REPORT={'phase':PHASE,'checks':[],'slicer_version':slicer.app.applicationVersion,
            'slicer_revision':slicer.app.repositoryRevision,'platform':platform.platform(),
            'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope':'Ordinary reader/draft job using visible Qt controls and actual native VTK effects; injected events, not OS/human/anatomical/Windows acceptance.'}
    try:
        if PHASE=='smoke':
            smoke()
        elif PHASE=='workflow':
            workflow()
        elif PHASE=='resume':
            resume()
        elif PHASE=='journal-write':
            journal_write()
        elif PHASE=='journal-resume':
            journal_resume()
        elif PHASE in ('legacy','legacy-regions'):
            legacy()
        elif PHASE=='orientation':
            orientation()
        elif PHASE=='layout':
            layout()
        elif PHASE=='guide':
            guide()
        else:
            raise ValueError('Unknown repair test phase '+PHASE)
        REPORT['passed']=True
    except Exception:
        REPORT['passed']=False
        REPORT['error']=traceback.format_exc()
        if WIDGET:
            REPORT['diagnostic']=getattr(WIDGET,'_diagnostic','')
            slicer.util.mainWindow().grab().save(str(OUTPUT/('repair-failure-'+PHASE+'.png')))
            try:
                WIDGET._loading=True
                WIDGET.dirty=False
                WIDGET.closeCase()
            except Exception:
                REPORT['cleanup_error']=traceback.format_exc()
    REPORT['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    destination=OUTPUT/('repair-'+PHASE+'.json')
    destination.write_text(json.dumps(REPORT,indent=2)+'\n')
    print('MENISCUS_REPAIR_RESULT',json.dumps({'passed':REPORT['passed'],'checks':len(REPORT['checks']),'report':str(destination)}),flush=True)
    if exit_application and PHASE=='journal-write' and REPORT['passed']:
        sys.stdout.flush()
        os._exit(0) # intentionally skip only this QA process's application cleanup
    if exit_application:
        slicer.app.exit(0 if REPORT['passed'] else 1)
    return REPORT


if __name__=='__main__':
    run_phase()
