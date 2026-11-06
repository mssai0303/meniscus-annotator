"""Installed-package health check, invoked only by maintainer CI environment."""
import json
import os
from pathlib import Path
import sys
import traceback
import slicer
receipt = {'passed': False, 'scope': 'Installed Windows runtime imports/identity only; no rendering or anatomical acceptance.'}
exit_code = 1
try:
    import nibabel
    import numpy
    import SimpleITK
    import MeniscusAnnotatorLib
    root = Path(__file__).resolve().parent
    assert Path(MeniscusAnnotatorLib.__file__).resolve().is_relative_to(root)
    assert MeniscusAnnotatorLib.APP_VERSION == '0.1.0'
    assert nibabel.__version__ == '5.3.2'
    assert slicer.app.applicationVersion == '5.12.4'
    assert slicer.app.repositoryRevision in ('4e21c19', '4e21c19d8360242d88d6ca2490bf52400441b8e1')
    receipt.update(passed=True, application_version=MeniscusAnnotatorLib.APP_VERSION,
                   runtime_version=slicer.app.applicationVersion,
                   runtime_revision=slicer.app.repositoryRevision,
                   runtime_name=slicer.app.applicationName,
                   python=sys.version, numpy=numpy.__version__, nibabel=nibabel.__version__,
                   SimpleITK=SimpleITK.Version_VersionString())
    exit_code = 0
except Exception:
    receipt['error'] = traceback.format_exc()
    print(receipt['error'])
finally:
    try:
        Path(os.environ['MENISCUS_PACKAGE_CHECK']).write_text(json.dumps(receipt, indent=2))
    finally:
        slicer.app.exit(exit_code)
