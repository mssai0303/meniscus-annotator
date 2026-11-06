# Maintained source-input preparation tools

These are the maintained source-input and package-verification tools deployed to
the private preparation workspace. Only source and synthetic tests belong here.
Never add MRI data, actual participant identifiers, clinical selection tables,
private manifests, migration records, source logs or package receipts to Git.

`package_layout.py` defines canonical `flat` and `legacy` folder names from the
unchanged case metadata. Flat folders contain exactly `image.nii.gz`, `case.json`
and `slice_review.csv`. Only the legacy layout may contain a known empty
`annotations` directory. Annotation content is never removed by these tools.

`native_mri_package.py` is the maintained acquired-grid DICOM input exporter and
NIfTI checker. This folder-layout change does not require exporting an existing
MRI again. `assemble_and_check_package.py` validates the original MRI/grid/source
binding, full slice table and package byte manifest. It accepts either uniform
layout; mixed layouts are rejected.

For a package whose README and index were already migrated, use:

```
python assemble_and_check_package.py --package PACKAGE --selection PRIVATE_SELECTION \
  --reports PRIVATE_SOURCE_REPORTS --receipt NEW_PRIVATE_RECEIPT --verify-existing
```

This writes a new private receipt without rewriting source package files. Use
`--check-only` with that receipt after copying. Old receipts remain historical
records of the old paths. Do not overwrite them merely to shorten folder names.

`list_verified_transfer_files.py --workspace PRIVATE_WORKSPACE --package PACKAGE`
uses current index paths even when immutable original export reports still name
the legacy layout. `make_export_batches.py` uses flat paths for future exports
from a supplied fixed selection and refuses existing frozen files. Neither tool
selects participants or changes case identities. The batch runner uses
`MRI_PREPARATION_WORKSPACE` (or the deployed script's parent workspace) and reads
only permission-gated source cases under that workspace.

Dependencies: NumPy, pydicom and SimpleITK. Tests in `tests/preparation` generate
small synthetic DICOM data and temporary folder fixtures; they make no anatomical
validity or Windows-runtime claim.

These are analyst tools, separate from the desktop runtime. Install their pinned
optional dependencies from `tools/preparation/requirements.txt` in a test environment
before running `python -m pytest tests/preparation -q`; the desktop core-only test
environment does not need these DICOM-export dependencies. Existing deployment
copies in a preparation workspace must remain byte-identical to this source tree.
