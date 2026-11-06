"""Maintainer build-tree health check. Executed with bundled Slicer Python."""
import json
import os
from pathlib import Path
import sys
import traceback
import slicer

receipt = {'passed': False}
exit_code = 1
try:
    import nibabel
    import numpy
    import SimpleITK
    import MeniscusAnnotatorLib
    assert Path(MeniscusAnnotatorLib.__file__).resolve().is_relative_to(Path(os.environ['MENISCUS_RUNTIME_ROOT']).resolve()), 'Core module loaded from source checkout instead of bundled runtime'
    assert nibabel.__version__ == '5.3.2', 'Unexpected nibabel version'
    assert slicer.app.applicationVersion == '0.1.0', 'Custom application branding/version mismatch'
    assert slicer.app.repositoryRevision in ('4e21c19', '4e21c19d8360242d88d6ca2490bf52400441b8e1'), 'Underlying Slicer revision mismatch'
    receipt.update(passed=True, application=slicer.app.applicationVersion,
                   slicer_commit=slicer.app.repositoryRevision,
                   python=sys.version, numpy=numpy.__version__,
                   nibabel=nibabel.__version__, SimpleITK=SimpleITK.Version_VersionString(),
                   core_module_path=MeniscusAnnotatorLib.__file__)
    exit_code = 0
except Exception:
    receipt['error'] = traceback.format_exc()
    print(receipt['error'])
finally:
    try:
        Path(os.environ['MENISCUS_RUNTIME_RECEIPT']).write_text(json.dumps(receipt, indent=2))
    finally:
        slicer.app.exit(exit_code)
