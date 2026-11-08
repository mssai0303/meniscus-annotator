"""Bounded installed-runtime graphics probe, synthetic pixels only.

This is a maintainer CI script, never a reader startup dependency. The caller
selects an actual available OpenGL implementation; capabilities are not spoofed.
"""
import json
import os
from pathlib import Path
import platform
import re
import traceback

import numpy as np
import qt
import slicer
import vtk
from vtk.util.numpy_support import vtk_to_numpy

OUTPUT = Path(os.environ['MENISCUS_GRAPHICS_PROBE_OUTPUT'])
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
REPORT = {
    'schema_version': 'meniscus_installed_graphics_probe/1', 'passed': False,
    'scope': 'Synthetic installed runtime rendering in an ephemeral maintainer environment; not human Windows acceptance',
    'mode': os.environ.get('MENISCUS_GRAPHICS_PROBE_MODE', 'system'),
    'platform': platform.platform(), 'machine': platform.machine(),
    'slicer_version': slicer.app.applicationVersion,
    'environment': {key: os.environ.get(key) for key in
                    ('QT_OPENGL', 'QT_OPENGL_DLL', 'LIBGL_ALWAYS_SOFTWARE',
                     'MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE')},
    'stage': 'python_entry',
}


def record(stage):
    REPORT['stage'] = stage
    OUTPUT.write_text(json.dumps(REPORT, indent=2) + '\n', encoding='utf-8')


def run():
    try:
        record('python_entry')
        if any(os.environ.get(key) for key in
               ('MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE')):
            raise RuntimeError('Graphics capability overrides are prohibited in this probe.')
        layout = slicer.app.layoutManager()
        layout.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        slicer.util.mainWindow().resize(1100, 760)
        slicer.util.mainWindow().show()
        record('layout_created')
        volume = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', 'SYNTHETIC graphics probe')
        k, j, i = np.indices((7, 72, 96))
        image = (i + 2 * j + 30 * (((i - 48) / 24) ** 2 + ((j - 36) / 18) ** 2 < 1)).astype(np.int16)
        slicer.util.updateVolumeFromArray(volume, image)
        volume.SetSpacing(.5, .6, 3.)
        volume.CreateDefaultDisplayNodes()
        display = volume.GetDisplayNode()
        display.SetAutoWindowLevel(False)
        display.SetWindowLevel(260, 120)
        slicer.util.setSliceViewerLayers(background=volume)
        widget = layout.sliceWidget('Red')
        widget.mrmlSliceNode().SetOrientationToAxial()
        slicer.util.resetSliceViews()
        widget.sliceLogic().SetSliceOffset(9.)
        slicer.app.processEvents()
        record('before_render')
        view = widget.sliceView()
        view.forceRender()
        window = view.renderWindow()
        capabilities = window.ReportCapabilities()
        REPORT['capabilities'] = capabilities
        match = re.search(r'OpenGL version string:\s*(\d+)\.(\d+)', capabilities)
        version = [int(match.group(1)), int(match.group(2))] if match else None
        REPORT['actual_opengl_version'] = version
        REPORT['render_window_class'] = window.GetClassName()
        # In vtkGenericOpenGLRenderWindow this is an embedding callback whose
        # status starts at zero, not an independent hardware/version test.
        # Gate on this window's actual GL strings and rendered pixels instead.
        REPORT['vtk_supports_opengl_callback'] = bool(window.SupportsOpenGL())
        record('rendered')
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        data = capture.GetOutput()
        width, height, _ = data.GetDimensions()
        pixels = vtk_to_numpy(data.GetPointData().GetScalars()).reshape(height, width, 3)
        centre = pixels[height // 3:2 * height // 3, width // 3:2 * width // 3]
        REPORT.update(rendered_size=[width, height], centre_pixel_std=float(centre.std()),
                      centre_pixel_range=[int(centre.min()), int(centre.max())])
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(OUTPUT.with_suffix('.png')))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        REPORT['passed'] = bool(version and tuple(version) >= (3, 2)
                                and width > 100 and height > 100 and centre.std() > 5)
        if not REPORT['passed']:
            REPORT['reason'] = 'Actual OpenGL 3.2 support and varied synthetic MRI-view pixels are required.'
        record('completed')
    except Exception:
        REPORT['error'] = traceback.format_exc()
        record('failed')
    slicer.app.exit(0 if REPORT['passed'] else 1)


qt.QTimer.singleShot(0, run)
