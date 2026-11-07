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

## Existing automated correction inputs

`prepare_starting_mask.py` reads a checksum-bound original binary whole-OAI
prediction and its exact matched MRI. It requires unchanged sibling `case.json`,
the frozen existing pipeline split/cut and medial-low assignment, recorded LPS
compartment centroids, pipeline/model provenance, and original prediction hash.
The existing split is reproduced on the original source grid and checked against
the knee side and physical LPS centroids. No new cut is estimated. A whole-only
prediction without an existing anatomical split is unresolved, never a blank
or invented 0/1/2 segmentation.

The categorical source is sampled onto the complete MRI reference using a
nearest-neighbour identity physical transform. Original prediction and MRI
bytes are preserved. The result is checked independently at target voxel
centres, saved/reopened and required to have the original MRI dimensions and
physical grid, explicit millimetres and consistent active qform/sform.
Private reports quantify source/native label counts, volumes, and categorical
round-trip changes caused by sampling between acquired planes. No fragment
filtering, smoothing, hole filling or anatomical repair occurs. Passing these
checks does not establish anatomical accuracy or expert-reviewed background.

```
python prepare_starting_mask.py --mri CASE/image.nii.gz --prediction ORIGINAL \
  --source-json PRIVATE_BOUND_CONTEXT --output CASE/starting_mask.nii.gz \
  --provenance CASE/starting_mask.json --private-report PRIVATE_REPORT
```

Required context keys are `case_key`, `source_series_key`,
`series_instance_uid`, `image_sha256`, `knee_side`, `source_prediction`
(`sha256`, `pipeline_version`, `model_version`, `identity`), and
`existing_split` (`split_cut_plane`, `medial_is_low_index`, `split_method`,
`x_low_index_mm`, `x_high_index_mm`). Existing source dimensions may be provided
as `source_grid_dimensions_xyz` (or `expected_source_dimensions_xyz`). These
come from the matched frozen pipeline record, not a guessed resize. Prepared
mask provenance is `meniscus_starting_mask/1`, explicitly marked
`unreviewed_automated_prediction`. Existing case/review files are never edited.

For a prepared correction package, keep the three original case files unchanged
and add `starting_mask.nii.gz` plus `starting_mask.json`. The root
`correction_job.json` uses `meniscus_job/1`, exact dataset identity, explicit
correction mode for every case, and portable mask paths relative to the package.
The sidecar binds the unchanged MRI/case/series identity, original prediction
checksum/version, prepared mask hash, transformation and technical verification.
It is explicitly unreviewed; source annotation/slice-review status never advances.

```
python assemble_and_check_package.py --package PACKAGE --selection PRIVATE_SELECTION \
  --reports PRIVATE_SOURCE_REPORTS --receipt NEW_PRIVATE_RECEIPT \
  --verify-existing --layout flat --correction
```

Strict correction verification rejects an unavailable prediction. If an original
prediction cannot establish the requested categorical labels, preserve the MRI
case and add only an explicit unresolved `starting_mask.json`, never an empty
mask. Its job rule is correction mode with `availability: unresolved`, a specific
reason and `starting_mask: null`. Deliberate `--allow-unresolved` verification
records ready/unresolved counts and `correction_package_complete: false`; it does
not turn that partial package into a completed correction dataset. The application
blocks opening the unresolved case before creating case work, while ready cases
remain usable. Run `tools/check_correction_inputs.py` through the application
core as an independent read-only contract check; no annotation work is created.
