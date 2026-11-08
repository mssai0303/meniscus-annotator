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
    from MeniscusAnnotatorLib import regions as regional
    root = Path(__file__).resolve().parent
    distribution = json.loads((root / 'distribution.json').read_text(encoding='utf-8'))
    from MeniscusAnnotatorLib.build_identity import capture_source_identity
    source_identity = capture_source_identity()
    assert source_identity.get('packaged_source_matches') is True
    assert source_identity['application_source_sha256'] == distribution['application_source_sha256']
    assert source_identity['application_commit'] == distribution['application_commit']
    assert Path(MeniscusAnnotatorLib.__file__).resolve().is_relative_to(root)
    assert Path(regional.__file__).resolve().is_relative_to(root)
    assert MeniscusAnnotatorLib.APP_VERSION == '0.1.0'
    assert nibabel.__version__ == '5.3.2'
    assert slicer.app.applicationVersion == '5.12.4'
    assert slicer.app.repositoryRevision in ('4e21c19', '4e21c19d8360242d88d6ca2490bf52400441b8e1')
    assert [item['value'] for item in regional.REGIONS] == [1, 2, 3, 4, 5, 6]
    assert regional.REGIONAL_PROTOCOL['status'] == 'pending_expert_protocol'
    phantom = numpy.array([[[0, 1, 2]]], dtype=numpy.uint8)
    assert numpy.array_equal(regional.initialize(phantom), numpy.array([[[0, 7, 8]]], dtype=numpy.uint8))
    receipt.update(passed=True, application_version=MeniscusAnnotatorLib.APP_VERSION,
                   runtime_version=slicer.app.applicationVersion,
                   runtime_revision=slicer.app.repositoryRevision,
                   runtime_name=slicer.app.applicationName,
                   application_commit=distribution['application_commit'],
                   application_source_sha256=distribution['application_source_sha256'],
                   application_source_dirty=distribution['application_source_dirty'],
                   packaged_source_matches=source_identity['packaged_source_matches'],
                   python=sys.version, numpy=numpy.__version__, nibabel=nibabel.__version__,
                   SimpleITK=SimpleITK.Version_VersionString(),
                   regional_extension_schema=regional.EXTENSION_SCHEMA,
                   regional_protocol_status=regional.REGIONAL_PROTOCOL['status'],
                   regional_import_and_unassigned_initialization='PASSED: synthetic memory arrays only; no regional assignment or acceptance',
                   regional_research_approval=False)
    exit_code = 0
except Exception:
    receipt['error'] = traceback.format_exc()
    print(receipt['error'])
finally:
    try:
        Path(os.environ['MENISCUS_PACKAGE_CHECK']).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    finally:
        slicer.app.exit(exit_code)
