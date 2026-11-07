# Horizon compatibility check

This is a staged check of an ordinary-user Horizon session and the pinned official Slicer runtime. It is **not** verification of the custom Meniscus Annotator installer or the annotation/export workflow.

## Sanitized observations reported by the user

- Horizon Windows 10 Enterprise, build 19045, x64; 16 GB RAM; NVIDIA A16 reported by the environment.
- Windows PowerShell 5.1, running without elevation.
- Documents and LocalAppData resolve to local `C:` locations rather than UNC paths. Ordinary-user write/read-back/checksum checks passed in both.
- Both test files survived Horizon disconnect/reconnect and Windows sign-out/new-login with unchanged checksums.
- The official Slicer 5.12.4 installer download was 268,839,640 bytes and matched the published SHA512. It was installed for the current user in a short ASCII LocalAppData directory.
- The user reported a responding GUI process with the title `3D Slicer 5.12.4`.

No account name, full private path, marker identifier or user-specific checksum is retained here. Windows 11, desktop recomposition, synthetic rendering, custom-module interaction and the actual custom installer still require their respective checks. No MRI or participant records are used in this procedure.

## Basic synthetic rendering probe

The maintained source is `tools/windows_render_probe.py`. It requires only the installed Slicer runtime's bundled NumPy, SimpleITK, Qt and VTK. The script generates a clearly synthetic 96×80×23 volume with anisotropic spacing and oblique acquired sagittal planes, saves it through native Slicer NIfTI storage, then reopens it with SimpleITK and checks exact voxel values plus dimensions, spacing, LPS origin and direction. After Qt rendering starts, it records the live OpenGL vendor, renderer and version in JSON. The application stays open for visual inspection.

The macOS development API check passed with Slicer 5.12.4 under Rosetta, including saved geometry and a live Apple M4 rendering context. This does not establish Windows rendering compatibility.

Before running this next step, close the empty Slicer window from the preceding launch check. Paste the following block into the same ordinary Windows PowerShell session. It does not install Python, download dependencies or access MRI. The only written files are the local synthetic probe, synthetic NIfTI and its JSON report.

```powershell
$out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('Meniscus_Horizon_probe_' + (Get-Date -Format yyyyMMdd_HHmmss))
New-Item -ItemType Directory -Path $out | Out-Null
$env:MENISCUS_RENDER_OUTPUT = $out
$probe = Join-Path $out 'render_probe.py'
$py = @'
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

'@
[IO.File]::WriteAllText($probe, $py, [Text.UTF8Encoding]::new($false))
$slicer = Join-Path $env:LOCALAPPDATA 'SlicerCompat-5.12.4\Slicer.exe'
if (-not (Test-Path -LiteralPath $slicer)) { throw 'The verified Slicer compatibility installation was not found.' }
Start-Process -FilePath $slicer -ArgumentList @('--ignore-slicerrc','--no-splash','--python-script',('"{0}"' -f $probe))
Write-Host "Report folder: $out"
```

Wait for the synthetic image to appear, then confirm that the image is visible and responds to zoom/pan and scrolling. Native controls may display physical offsets; the report explicitly records all 23 acquired planes and the technical index convention. This simple runtime probe does not implement the application's restricted acquired-plane navigation or segmentation editor.

Once the image has appeared, this separate short command displays the result:

```powershell
Get-Content -LiteralPath (Join-Path $out 'render-probe.json') -Raw
```

A successful technical result contains `passed: true` and `render_context_reported: true`, with vendor/renderer/version fields. A missing report or a black/unresponsive image requires investigation even if a GUI process exists. Record Windows results as user-reported until the report and visual observations are received. Do not use this result to claim that native annotation, approval, export, offline custom-app launch or clean installation passed.
