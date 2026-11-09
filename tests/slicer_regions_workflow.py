"""Native Slicer regional draft workflow on eight procedural synthetic grids.

MENISCUS_REGIONS_OUTPUT must name an isolated folder outside the repository.
Phases: workflow (fresh fixtures), resume (same output, fresh process), legacy.
This is injected Qt/VTK desktop testing, never anatomical or human acceptance.
Installed TestKit callers may invoke run_phase(exit_application=False).
"""
import copy
import csv
import datetime
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import traceback
import zipfile

import nibabel as nib
import numpy as np
import qt
import SimpleITK as sitk
import slicer

OUTPUT = Path(os.environ['MENISCUS_REGIONS_OUTPUT']).resolve()
PHASE = os.environ.get('MENISCUS_REGIONS_PHASE', 'workflow')
os.environ.setdefault('MENISCUS_DRAW_OUTPUT', str(OUTPUT))
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
import slicer_draw_workflow as d
from MeniscusAnnotatorLib.core import Dataset, WorkStore, sha256, load_job_config
from MeniscusAnnotatorLib.regions import REGIONS, initialize, completion_errors

REPORT = {}
WIDGET = None


def check(name, value, detail=None):
    d.check(name, value, detail)


def regional(widget):
    return tuple(a.copy() for a in widget.collectRegionalArrays())


def all_arrays(widget):
    return (*d.arrays(widget), *regional(widget))


def select(widget, parent, region='anterior'):
    widget.taskCombo.setCurrentIndex(1)
    widget.labelButtons[parent].click()
    widget.regionCombo.setCurrentIndex(('anterior', 'body', 'posterior').index(region))
    d.events()
    check('explicit region target ' + parent + '_' + region,
          widget.annotationTask == 'regions' and widget._editingTargetID() == parent + '_' + region)


def draw(widget, vertices, parent):
    d.points(widget, vertices, parent)
    d.right_click(widget, vertices[-1])


def stroke(widget, point, parent, tool='Paint', diameter=1.2):
    d.stroke(widget, point, parent, tool, diameter)


def undo_redo(widget, before, after, name):
    d.button('Undo').click()
    d.events()
    check(name + ' exact Undo across all native segments', d.same(all_arrays(widget), before))
    d.button('Redo').click()
    d.events()
    check(name + ' exact Redo across all native segments', d.same(all_arrays(widget), after))


def verify_regional_saved(widget, checkpoint, expected, prefix):
    case = widget.session.case
    manifest = json.loads((checkpoint / 'manifest.json').read_text())
    regional_files={'regions.nii.gz','regional_uncertainty.nii.gz','regional_validity.nii.gz','regions.json','regional_review.csv'}
    check(prefix+' all five regional payload hashes verified',
          regional_files.issubset(manifest['files_sha256'])
          and all(manifest['files_sha256'][name]==sha256(checkpoint/name) for name in regional_files))
    check(prefix + ' versioned explicit pending regional extension',
          manifest['regional_extension'] == {'schema_version': 'meniscus_regional_extension/1',
              'protocol_status': 'pending_expert_protocol', 'research_approved': False})
    for name, expected_array in [('regions.nii.gz', expected[0]),
                                 ('regional_uncertainty.nii.gz', expected[1]),
                                 ('regional_validity.nii.gz', np.zeros_like(expected[0]))]:
        image = nib.load(str(checkpoint / name))
        check(prefix + ' native full-grid values and physical geometry ' + name,
              np.array_equal(np.asarray(image.dataobj).transpose(2, 1, 0), expected_array)
              and image.shape == case.shape_xyz
              and np.allclose(image.affine, case.affine_ras, atol=1e-4)
              and image.header.get_xyzt_units()[0] == 'mm')
        independent = sitk.ReadImage(str(checkpoint / name))
        check(prefix + ' independent SimpleITK region/grid ' + name,
              np.array_equal(sitk.GetArrayFromImage(independent), expected_array)
              and np.allclose(independent.GetSpacing(), case.metadata['spacing_xyz_mm'], atol=1e-5)
              and np.allclose(independent.GetOrigin(), case.metadata['origin_lps_mm'], atol=1e-4)
              and np.allclose(np.array(independent.GetDirection()).reshape(3, 3),
                              case.metadata['direction_lps_columns'], atol=1e-5))
    state = json.loads((checkpoint / 'regions.json').read_text())
    check(prefix + ' regional draft not research approved and complete slice records',
          state['status'] == 'draft' and state['research_approved'] is False
          and state['approval'] is None and state['protocol']['status'] == 'pending_expert_protocol'
          and len(state['review']) == case.n_slices
          and state['annotator'] == 'Software QA (automated)')
    with (checkpoint/'regional_review.csv').open(newline='',encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream))
    check(prefix+' review CSV covers every acquired index including empty slices',
          len(rows)==case.n_slices
          and [int(row['slice_index']) for row in rows]==list(range(case.n_slices))
          and [int(row['displayed_slice']) for row in rows]==list(range(1,case.n_slices+1)))
    reopened = slicer.util.loadSegmentation(str(checkpoint / 'segmentation.seg.nrrd'))
    check(prefix + ' all ten editable native segments retained', reopened is not None
          and reopened.GetSegmentation().GetNumberOfSegments() == 10)
    if reopened:
        try:
            for item in REGIONS:
                value = slicer.util.arrayFromSegmentBinaryLabelmap(reopened, item['id'], widget.volume)
                check(prefix + ' exact editable region ' + item['id'],
                      np.array_equal(value != 0, expected[0] == item['value']))
            value = slicer.util.arrayFromSegmentBinaryLabelmap(reopened, 'regional_uncertain', widget.volume)
            check(prefix + ' editable independent regional uncertainty',
                  np.array_equal(value != 0, expected[1] != 0))
        finally:
            helpers = [reopened.GetDisplayNode(), reopened.GetStorageNode()]
            slicer.mrmlScene.RemoveNode(reopened)
            for node in helpers:
                if node:
                    slicer.mrmlScene.RemoveNode(node)


def pending_transitions(widget, parent, center):
    x, y, k = center
    widget.toolButtons['Draw'].click()
    before = all_arrays(widget)
    vertices = [(x-1, y-1, k), (x+1, y-1, k), (x, y+1, k)]
    d.points(widget, vertices, parent)
    check('regional native contour has three pending points', d.pending_points(widget) == 3)
    widget.taskCombo.setCurrentIndex(0)
    d.events()
    check('pending contour blocks and reverts annotation task switch',
          widget.annotationTask == 'regions' and widget.taskCombo.currentIndex == 1
          and d.pending_points(widget) == 3 and d.same(all_arrays(widget), before))
    original = widget.activeRegion
    widget.regionCombo.setCurrentIndex(2 if original != 'posterior' else 0)
    d.events()
    check('pending contour blocks and reverts regional target switch',
          widget.activeRegion == original
          and widget.regionCombo.currentIndex == ('anterior','body','posterior').index(original)
          and d.pending_points(widget) == 3 and d.same(all_arrays(widget), before))
    other = 'lateral' if parent == 'medial' else 'medial'
    widget.labelButtons[other].click()
    widget.boundaryUncertainButton.click()
    d.events()
    check('pending contour blocks parent and boundary-uncertainty target changes',
          widget._parentCompartment() == parent and not widget._regionBoundary
          and d.pending_points(widget) == 3 and d.same(all_arrays(widget), before))
    d.discard(widget, False)
    check('Keep drawing preserves pending regional points and arrays',
          d.pending_points(widget) == 3 and d.same(all_arrays(widget), before))
    d.discard(widget, True)
    check('explicit regional Discard leaves committed arrays unchanged',
          d.pending_points(widget) == 0 and d.same(all_arrays(widget), before))


def notes_shortcuts(widget):
    widget.regionalAssessmentPanel.collapsed = False
    d.events()
    widget.regionNotes.setPlainText('')
    fired = []
    callbacks = []
    for i, shortcut in enumerate(widget.shortcuts):
        callback = lambda i=i: fired.append(i)
        shortcut.connect('activated()', callback)
        callbacks.append((shortcut, callback))
    before = all_arrays(widget)
    k, target, effect = widget.currentSlice, widget._editingTargetID(), widget.editor.activeEffect().name
    try:
        text = 'dep123rufa'
        for char in text:
            d.key(widget.regionNotes, ord(char.upper()), char)
        check('regional notes retain typed order and cursor after each refresh',
              str(widget.regionNotes.toPlainText()) == text
              and widget.regionNotes.textCursor().position() == len(text))
        check('editing shortcuts stay inactive while typing regional notes',
              not fired and widget.currentSlice == k and widget._editingTargetID() == target
              and widget.editor.activeEffect().name == effect and d.same(all_arrays(widget), before))
    finally:
        for shortcut, callback in callbacks:
            shortcut.disconnect('activated()', callback)
    widget.regionNotes.setPlainText('SYNTHETIC SOFTWARE PRACTICE. No anatomical assessment.')


def workflow(exit_application):
    global WIDGET
    source = OUTPUT / 'Synthetic source 空間'
    work = OUTPUT / 'Synthetic regional work'
    check('workflow requires a fresh synthetic output', not source.exists() and not work.exists())
    _, truth = d.make_draw_matrix(source)
    hashes = {p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()}
    (OUTPUT / 'source-hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    expected_dir = OUTPUT / 'Expected'
    expected_dir.mkdir()
    WIDGET = widget = d.open_widget(source, work)
    window = slicer.util.mainWindow()
    window.showNormal()
    d.events()
    window.resize(1280, 800)
    d.events()
    widget.autosave.stop()
    dataset = widget.dataset
    expected = {}
    expected_state = {}
    keys = list(truth)
    for ordinal, key_value in enumerate(keys):
        d.open_case_ui(widget, key_value)
        item = truth[key_value]
        whole = d.arrays(widget)
        initial = regional(widget)
        check(key_value + ' explicit unassigned initialization without horn inference',
              np.array_equal(initial[0], initialize(whole[0])) and not initial[1].any())
        check(key_value + ' all ten native IDs and stable whole mapping',
              widget.anatomy.GetSegmentation().GetNumberOfSegments() == 10
              and all(widget.anatomy.GetSegmentation().GetSegment(x) is not None
                      for x in ('medial','lateral','uncertain','regional_uncertain',*[r['id'] for r in REGIONS])))
        for k in range(widget.session.case.n_slices):
            widget.sliceSlider.setValue(k+1)
            d.events()
            widget.reviewButton.click()
            d.events()
        widget.caseReviewPanel.collapsed = False
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        d.approve(widget)
        approval = copy.deepcopy(widget.session.state['approval'])
        check(key_value + ' whole practice approval distinct from regional draft',
              widget.session.state['status'] == 'practice_approved'
              and widget.regionalState['research_approved'] is False)
        widget.caseReviewPanel.collapsed = True
        primary_review = copy.deepcopy(widget.session.state['review'])
        for parent, offset, unassigned in [('medial',0,7),('lateral',3,8)]:
            seed = item[parent + '_seed_ijk']
            x, y, k = seed
            widget.goSlice(k)
            select(widget, parent)
            check(key_value + ' ' + parent + ' native edit mask targets parent',
                  widget.editorNode.GetMaskSegmentID() == parent
                  and widget.editorNode.GetMaskMode() == slicer.vtkMRMLSegmentationNode.EditAllowedInsideSingleSegment,
                  {'mode':widget.editorNode.GetMaskMode(), 'everywhere':slicer.vtkMRMLSegmentationNode.EditAllowedEverywhere,
                   'inside_one':slicer.vtkMRMLSegmentationNode.EditAllowedInsideSingleSegment})
            # A contour wholly outside either parent must not create assignments
            # or alter original whole-meniscus tissue.
            outside_before = all_arrays(widget)
            draw(widget, [(42,34,k),(48,34,k),(48,40,k),(42,40,k)], parent)
            check(key_value + ' ' + parent + ' native region Draw constrained outside parent',
                  d.same(all_arrays(widget), outside_before) and d.pending_points(widget) == 0)
            widget.regionStatusCombo.setCurrentIndex(2)
            d.events()
            check(key_value + ' absent can be recorded only on empty selected region',
                  widget.regionalState['assessments'][parent+'_anterior']['status'] == 'absent')
            before = all_arrays(widget)
            vertices = [(x-2,y-2,k),(x+2,y-2,k),(x+2,y+2,k),(x-2,y+2,k)]
            draw(widget, vertices, parent)
            after = all_arrays(widget)
            changed = after[2] != before[2]
            check(key_value + ' ' + parent + ' right-click fills selected regional slice',
                  changed.any() and np.flatnonzero(np.any(changed, axis=(1,2))).tolist() == [k]
                  and np.all(after[2][changed] == offset+1)
                  and d.same(after[:2], whole))
            check(key_value + ' Draw after absent requires new assessment, never infers present',
                  widget.regionalState['assessments'][parent+'_anterior']['status'] == 'unassessed')
            undo_redo(widget, before, after, key_value+' '+parent+' region Draw')
            widget.regionStatusCombo.setCurrentIndex(1)
            d.events()
            widget.reviewButton.click()
            d.events()
            check(key_value+' explicit regional review only selected parent',
                  widget.regionalState['review'][k][parent+'_reviewed']
                  and not widget.regionalState['review'][k][('lateral' if parent=='medial' else 'medial')+'_reviewed']
                  and widget.session.state['review'] == primary_review)
            widget.goSlice(k)
            select(widget,parent,'body')
            before = all_arrays(widget)
            stroke(widget,seed,parent)
            after = all_arrays(widget)
            check(key_value+' '+parent+' Paint reassigns AH to body without parent change',
                  after[2][k,y,x] == offset+2 and d.same(after[:2],whole)
                  and not widget.regionalState['review'][k][parent+'_reviewed'])
            undo_redo(widget,before,after,key_value+' '+parent+' body Paint')
            before = all_arrays(widget)
            stroke(widget,seed,parent,'Erase')
            after = all_arrays(widget)
            check(key_value+' '+parent+' Erase returns assignment to explicit unassigned',
                  after[2][k,y,x] == unassigned and d.same(after[:2],whole))
            undo_redo(widget,before,after,key_value+' '+parent+' body Erase')
            # Native Undo restoring voxels conflicts with an explicit absence:
            # record absence after erase, then Undo must reset to unassessed.
            widget.regionStatusCombo.setCurrentIndex(2)
            d.events()
            d.button('Undo').click()
            d.events()
            check(key_value+' '+parent+' Undo restoring absent region resets assessment',
                  regional(widget)[0][k,y,x] == offset+2
                  and widget.regionalState['assessments'][parent+'_body']['status'] == 'unassessed'
                  and d.same(d.arrays(widget),whole))
            select(widget,parent,'posterior')
            stroke(widget,(x+1,y+1,k),parent)
            check(key_value+' '+parent+' posterior assignment fixed value',
                  regional(widget)[0][k,y+1,x+1] == offset+3 and d.same(d.arrays(widget),whole))
            before = all_arrays(widget)
            widget.boundaryUncertainButton.click()
            d.events()
            stroke(widget,seed,parent)
            after = all_arrays(widget)
            check(key_value+' '+parent+' boundary uncertainty separate from all label classes',
                  after[3][k,y,x] == 1 and np.array_equal(after[2],before[2])
                  and d.same(after[:2],whole))
            undo_redo(widget,before,after,key_value+' '+parent+' regional uncertainty')
            select(widget,parent,'anterior')
            pending_transitions(widget,parent,seed)
        notes_shortcuts(widget)
        flag_k=widget.currentSlice
        widget.regionalFlag.setChecked(True)
        d.events()
        check(key_value+' regional flag separate from whole-slice review',
              widget.regionalState['review'][flag_k]['flag']
              and widget.session.state['review']==primary_review)
        check(key_value+' whole labels and whole review untouched by regional edits',
              d.same(d.arrays(widget),whole) and widget.session.state['review'] == primary_review)
        check(key_value+' regional approval blocked while expert protocol pending',
              not widget.approveButton.enabled
              and any('protocol' in error.lower() for error in completion_errors(*d.arrays(widget),*regional(widget),widget.regionalState)))
        widget.saveButton.click()
        d.events()
        check(key_value+' Save draft stores regional work without changing whole approval',
              not widget.dirty and 'Saved' in str(widget.saveStatus.text)
              and widget.session.state['status'] == 'practice_approved'
              and widget.session.state['approval'] == approval)
        saved_whole, saved_region = d.arrays(widget), regional(widget)
        verify_regional_saved(widget,widget.session.current_checkpoint,saved_region,key_value+' save')
        # Whole edits are deliberate; regional children are clipped at exactly
        # those voxels, and a native Undo restores the combined ten-segment state.
        widget.taskCombo.setCurrentIndex(0)
        d.events()
        seed = item['medial_seed_ijk']
        x,y,k = seed
        widget.goSlice(k)
        before = all_arrays(widget)
        stroke(widget,seed,'medial','Erase')
        after = all_arrays(widget)
        check(key_value+' parent Erase clears dependent regions and uncertainty only where removed',
              after[0][k,y,x] == 0 and after[2][k,y,x] == 0 and after[3][k,y,x] == 0
              and not widget.session.state['review'][k]['reviewed'])
        undo_redo(widget,before,after,key_value+' parent Erase')
        d.button('Undo').click()
        d.events()
        check(key_value+' restored whole and regions exact after parent edit',
              d.same(d.arrays(widget),saved_whole) and d.same(regional(widget),saved_region))
        before=all_arrays(widget)
        stroke(widget,seed,'lateral','Paint')
        after=all_arrays(widget)
        check(key_value+' changing whole compartment clears old region without transferring anatomy',
              after[0][k,y,x]==2 and after[2][k,y,x]==8)
        undo_redo(widget,before,after,key_value+' whole compartment correction')
        d.button('Undo').click()
        d.events()
        check(key_value+' compartment correction Undo restores exact parent and region maps',
              d.same(d.arrays(widget),saved_whole) and d.same(regional(widget),saved_region))
        # Restore review through actual explicit controls, then practice approve.
        for k in range(widget.session.case.n_slices):
            widget.goSlice(k)
            if not widget.session.state['review'][k]['reviewed']:
                widget.reviewButton.click()
                d.events()
        widget.medialConsidered.setChecked(True)
        widget.lateralConsidered.setChecked(True)
        d.approve(widget)
        widget.caseReviewPanel.collapsed = True
        select(widget,'medial','anterior')
        widget.goSlice(item['medial_seed_ijk'][2])
        expected[key_value] = all_arrays(widget)
        expected_state[key_value] = copy.deepcopy(widget.regionalState)
        np.savez_compressed(expected_dir/(key_value+'.npz'),labels=expected[key_value][0],
                            uncertainty=expected[key_value][1],regions=expected[key_value][2],
                            regional_uncertainty=expected[key_value][3])
        if ordinal == 0:
            widget.regionalAssessmentPanel.collapsed = True
            widget.notesPanel.collapsed = True
            widget.toolButtons['Draw'].click()
            d.red().sliceView().interactorStyle().GetInteractor().InvokeEvent('LeaveEvent')
            window.resize(1280,800)
            d.events()
            d.red().sliceView().forceRender()
            screenshot = OUTPUT/'synthetic-regional-workflow.png'
            window.grab().save(str(screenshot))
            REPORT['regional_screenshot'] = str(screenshot)
        widget.saveButton.click()
        d.events()
        d.open_case_ui(widget,key_value)
        check(key_value+' current-process native saved-work reconnection exact',
              d.same(all_arrays(widget),expected[key_value]))
    archive_path = d.export_via_ui(widget)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('results.json'))
        check('all eight practice-approved whole cases exported with regional draft',
              len(manifest['cases']) == 8 and manifest['software_practice'] is True
              and manifest['accepted_research_annotation'] is False)
        check('MRI input is not duplicated into export',not any(name.endswith('image.nii.gz') for name in archive.namelist()))
        for record in manifest['cases']:
            key_value = record['case_key']
            case = dataset.by_key[key_value]
            for name,index in [('labels.nii.gz',0),('uncertainty.nii.gz',1),('regions.nii.gz',2),('regional_uncertainty.nii.gz',3)]:
                path = OUTPUT/('verify-export-'+key_value+'-'+name)
                path.write_bytes(archive.read(record['folder']+'/'+name))
                image = nib.load(str(path))
                check(key_value+' ZIP exact full grid '+name,
                      np.array_equal(np.asarray(image.dataobj).transpose(2,1,0),expected[key_value][index])
                      and image.shape == case.shape_xyz and np.allclose(image.affine,case.affine_ras,atol=1e-4))
            state = json.loads(archive.read(record['folder']+'/regions.json'))
            check(key_value+' ZIP region explicitly remains unapproved pending expert protocol',
                  state['status']=='draft' and state['research_approved'] is False
                  and state['protocol']['status']=='pending_expert_protocol')
            for parent in ('medial','lateral'):
                point=truth[key_value][parent+'_seed_ijk']
                check(key_value+' exported regional physical point '+parent,
                      np.allclose((image.affine@[*point,1])[:3],truth[key_value][parent+'_seed_ras_mm'],atol=1e-4))
    (OUTPUT/'expected-states.json').write_text(json.dumps(expected_state,indent=2)+'\n')
    (OUTPUT/'expected-cases.json').write_text(json.dumps(keys,indent=2)+'\n')
    check('all original synthetic source files unchanged byte for byte',
          hashes == {p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()})
    widget.settings.sync()
    widget.closeCase()
    check('regional workflow releases owned case lock',widget.session is None)


def resume():
    global WIDGET
    prior=json.loads((OUTPUT/'regions-workflow.json').read_text())
    check('cold restart requires successful regional native workflow',prior.get('passed') is True)
    WIDGET=widget=d.open_widget(OUTPUT/'Synthetic source 空間',OUTPUT/'Synthetic regional work')
    check('cold restart uses identical application and core source',
          REPORT['application_source_sha256']==prior['application_source_sha256']
          and REPORT['core_source_sha256']==prior['core_source_sha256'])
    keys=json.loads((OUTPUT/'expected-cases.json').read_text())
    truth=json.loads((OUTPUT/'Synthetic source 空間'/'synthetic_truth.json').read_text())
    expected_states=json.loads((OUTPUT/'expected-states.json').read_text())
    for key_value in keys:
        d.open_case_ui(widget,key_value)
        expected=np.load(OUTPUT/'Expected'/(key_value+'.npz'))
        values=tuple(expected[name] for name in ('labels','uncertainty','regions','regional_uncertainty'))
        check(key_value+' cold restart restores all whole and regional arrays exactly',d.same(all_arrays(widget),values))
        check(key_value+' cold restart restores explicit task, compartment and region',
              widget.annotationTask=='regions' and widget._parentCompartment()=='medial'
              and widget.activeRegion=='anterior')
        check(key_value+' cold restores regional assessments, notes, flags and separate review',
              all(widget.regionalState[field]==expected_states[key_value][field]
                  for field in ('assessments','review','notes','protocol','status','research_approved')))
        verify_regional_saved(widget,widget.session.current_checkpoint,values[2:],key_value+' cold')
        for parent in ('medial','lateral'):
            point=truth[key_value][parent+'_seed_ijk']
            check(key_value+' cold physical region coordinate '+parent,
                  np.allclose((widget.session.case.affine_ras@[*point,1])[:3],truth[key_value][parent+'_seed_ras_mm'],atol=1e-4))
    source=OUTPUT/'Synthetic source 空間'
    hashes=json.loads((OUTPUT/'source-hashes.json').read_text())
    check('cold restart leaves source untouched',hashes=={p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()})
    widget.closeCase()


def legacy():
    """Exercise the preserved six-file schema, not an invented historical run."""
    global WIDGET
    source, work = OUTPUT/'Legacy synthetic source', OUTPUT/'Legacy synthetic work'
    check('legacy-format fixture starts isolated',not source.exists() and not work.exists())
    dataset,truth=d.make_draw_matrix(source)
    job=load_job_config(source/'correction_job.json',dataset)
    store=WorkStore(work,dataset,job)
    case=dataset.cases[0]
    volume=slicer.util.loadVolume(str(case.folder/'image.nii.gz'))
    node=slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode','SYNTHETIC legacy three labels')
    node.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    with store.open_case(case) as session:
        labels,uncertain,_=session.load()
        for key,value in [('medial',labels==1),('lateral',labels==2),('uncertain',uncertain!=0)]:
            node.GetSegmentation().AddEmptySegment(key,key)
            slicer.util.updateSegmentBinaryLabelmapFromArray(value.astype(np.uint8),node,key,volume)
        def writer(path):
            storage=node.CreateDefaultStorageNode()
            slicer.mrmlScene.AddNode(storage)
            node.SetAndObserveStorageNodeID(storage.GetID())
            storage.SetCropToMinimumExtent(False)
            if not slicer.util.saveNode(node,str(path)):
                raise OSError('Synthetic legacy segmentation write failed')
        checkpoint=session.save(labels,uncertain,writer)
    # Current saves add research eligibility. Construct the preserved 0.1
    # six-file schema explicitly; no historical binary/reader is executed.
    old_state=json.loads((checkpoint/'annotation.json').read_text())
    old_state['app_version']='0.1.0'
    for field in ('approval_purpose','research_eligible','accepted_research_annotation'):
        old_state.pop(field,None)
    (checkpoint/'annotation.json').write_text(json.dumps(old_state,indent=2)+'\n')
    manifest=json.loads((checkpoint/'manifest.json').read_text())
    manifest.pop('research_eligibility',None)
    if 'research_eligibility.nii.gz' in manifest['files_sha256']:
        manifest['files_sha256'].pop('research_eligibility.nii.gz')
        (checkpoint/'research_eligibility.nii.gz').unlink()
    manifest['files_sha256']['annotation.json']=sha256(checkpoint/'annotation.json')
    (checkpoint/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    check('canonical legacy six-file checkpoint has no optional extension',
          len(manifest['files_sha256'])==6 and 'regional_extension' not in manifest)
    legacy_hashes={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()}
    for current in (node,volume):
        helpers=[current.GetDisplayNode(),current.GetStorageNode()]
        slicer.mrmlScene.RemoveNode(current)
        for helper in helpers:
            if helper:
                slicer.mrmlScene.RemoveNode(helper)
    WIDGET=widget=d.open_widget(source,work)
    d.open_case_ui(widget,case.key)
    check('new interface reopens legacy whole arrays exactly',d.same(d.arrays(widget),(labels,uncertain)))
    check('legacy reopen initializes only explicit unassigned regions',
          np.array_equal(regional(widget)[0],initialize(labels)) and not regional(widget)[1].any())
    check('opening legacy work does not rewrite original checkpoint',
          legacy_hashes=={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()})
    seed=truth[case.key]['medial_seed_ijk']
    widget.goSlice(seed[2])
    select(widget,'medial')
    stroke(widget,seed,'medial')
    expected=all_arrays(widget)
    widget.saveButton.click()
    d.events()
    check('first regional edit creates a separate versioned extended checkpoint',
          widget.session.current_checkpoint!=checkpoint
          and d.same(d.arrays(widget),(labels,uncertain)))
    verify_regional_saved(widget,widget.session.current_checkpoint,expected[2:],'legacy extension')
    widget.closeCase()
    d.open_case_ui(widget,case.key)
    check('extended legacy work reopens all native arrays exactly',d.same(all_arrays(widget),expected))
    check('legacy original immutable files remain byte-for-byte unchanged',
          legacy_hashes=={p.name:sha256(p) for p in checkpoint.iterdir() if p.is_file()})
    widget.closeCase()


def run_phase(exit_application=True):
    global REPORT
    for protected in (TEST_DIR.parent,Path(inspect.getsourcefile(Dataset)).resolve().parent.parent):
        try:
            OUTPUT.relative_to(protected)
        except ValueError:
            continue
        raise ValueError('Synthetic regional outputs must stay outside source/installed application.')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    REPORT={'phase':PHASE,'checks':[],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'slicer_version':slicer.app.applicationVersion,'slicer_revision':slicer.app.repositoryRevision,
            'platform':platform.platform(),'machine':platform.machine(),
            'scope':'Procedural synthetic software practice; injected actual Qt/VTK desktop events. Not anatomical/human/Windows acceptance.'}
    d.OUTPUT,d.PHASE,d.REPORT=OUTPUT,'regions_'+PHASE,REPORT
    destination=OUTPUT/('regions-'+PHASE+'.json')
    try:
        if PHASE=='workflow':
            workflow(exit_application)
        elif PHASE=='resume':
            resume()
        elif PHASE=='legacy':
            legacy()
        else:
            raise ValueError('Unknown regional test phase')
        check('application source unchanged during regional phase',
              sha256(REPORT['application_source_path'])==REPORT['application_source_sha256'])
        REPORT['passed']=True
    except Exception:
        REPORT['passed']=False
        REPORT['error']=traceback.format_exc()
        slicer.util.mainWindow().grab().save(str(OUTPUT/('synthetic-regional-failure-'+PHASE+'.png')))
        if WIDGET:
            try:
                for pipeline in WIDGET.editor.effectByName('Draw').self().drawPipelines.values():
                    pipeline.resetPolyData()
                WIDGET._loading=True
                WIDGET.dirty=False
                WIDGET.closeCase()
            except Exception:
                REPORT['cleanup_error']=traceback.format_exc()
    REPORT['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    destination.write_text(json.dumps(REPORT,indent=2)+'\n')
    print('MENISCUS_REGIONS_RESULT',json.dumps({'phase':PHASE,'passed':REPORT['passed'],
          'checks':len(REPORT['checks']),'report':str(destination)}),flush=True)
    if exit_application:
        slicer.app.exit(0 if REPORT['passed'] else 1)
    return REPORT


if __name__=='__main__':
    run_phase(exit_application=os.environ.get('MENISCUS_REGIONS_MANAGED')!='1')
