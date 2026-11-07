"""Synthetic Slicer render/geometry probe only; leaves the application open."""
import hashlib, json, os, tempfile
from pathlib import Path
import numpy as np
import SimpleITK as sitk
import qt, slicer, vtk
out = Path(os.environ.get('MENISCUS_RENDER_OUTPUT') or tempfile.mkdtemp(prefix='meniscus-render-'))
out.mkdir(parents=True, exist_ok=True)
k, j, i = np.indices((23, 80, 96), dtype=float)
r = ((i-47.5)/32)**2 + ((j-39.5)/27)**2
pixels = (900*np.exp(-2*r) + 450*np.exp(-((r-.65)/.08)**2) + 150*k/22).astype(np.int16)
a, b = np.deg2rad([13, 6])
ry = np.array([[np.cos(a),0,np.sin(a)],[0,1,0],[-np.sin(a),0,np.cos(a)]])
rz = np.array([[np.cos(b),-np.sin(b),0],[np.sin(b),np.cos(b),0],[0,0,1]])
direction = rz @ ry @ np.array([[0,0,1],[1,0,0],[0,1,0]])
spacing, origin = [.40,.45,3.0], [-32.,-40.,-20.]
lps = np.eye(4); lps[:3,:3] = direction @ np.diag(spacing); lps[:3,3] = origin
ras = np.diag([-1,-1,1,1]) @ lps
volume = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode','SYNTHETIC oblique 23 slices')
slicer.util.updateVolumeFromArray(volume,pixels)
matrix = vtk.vtkMatrix4x4(); slicer.util.updateVTKMatrixFromArray(matrix,ras); volume.SetIJKToRASMatrix(matrix)
path = out / 'synthetic-oblique-sagittal.nii.gz'
assert slicer.util.saveNode(volume,str(path)), 'Could not save synthetic NIfTI'
check = sitk.ReadImage(str(path))
assert np.array_equal(sitk.GetArrayFromImage(check),pixels), 'Saved voxel values changed'
assert check.GetSize()==(96,80,23) and np.allclose(check.GetSpacing(),spacing,atol=1e-5), 'Size/spacing changed'
assert np.allclose(check.GetOrigin(),origin,atol=1e-4) and np.allclose(np.array(check.GetDirection()).reshape(3,3),direction,atol=1e-5), 'Origin/direction changed'
slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
slicer.util.setSliceViewerLayers(background=volume)
view = slicer.app.layoutManager().sliceWidget('Red'); node = view.mrmlSliceNode()
plane = np.eye(4); plane[:3,:3] = ras[:3,:3]/np.asarray(spacing); plane[:3,3] = (ras @ [47.5,39.5,11,1])[:3]
slicer.util.updateVTKMatrixFromArray(node.GetSliceToRAS(),plane); node.UpdateMatrices(); view.sliceLogic().FitSliceToAll()
report = dict(passed=True, scope='Synthetic rendering and saved geometry only; not annotation or installer verification', slicer_version=slicer.app.applicationVersion, slicer_revision=slicer.app.repositoryRevision, dimensions_xyz=[96,80,23], spacing_xyz_mm=spacing, origin_lps_mm=origin, direction_lps_columns=direction.tolist(), slice_mapping='Displayed n=stored k+1; arrays KJI; 23 acquired planes', image_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def finish():
    view.sliceView().forceRender()
    caps = view.sliceView().renderWindow().ReportCapabilities()
    report['opengl'] = {line.split(':',1)[0].strip():line.split(':',1)[1].strip() for line in caps.splitlines() if ':' in line and any(t in line.lower() for t in ['vendor string','renderer string','version string'])}
    report['render_context_reported'] = bool(report['opengl'])
    (out/'render-probe.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('MENISCUS_RENDER_REPORT='+str(out/'render-probe.json'), flush=True)
qt.QTimer.singleShot(800,finish)
