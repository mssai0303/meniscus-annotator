# Regional loading example for technical reviewers

`tools/read_regional_annotation.py` is a small coordinator/developer example using
this application's native-grid and regional validation helpers. Jeff's routine
annotation/export workflow uses the desktop UI and does not require this tool or
a terminal. This example does not replace the maintained application acceptance
route, perform anatomical validation, or establish integration with an actual
training pipeline.

The Windows review package includes this optional example in `Examples` and the
same application helpers under `lib/Slicer-5.12/qt-scripted-modules`. The example
locates that installed module path without duplicating the application code.
It requires a technical reviewer's Python environment with the pinned NumPy and
nibabel dependencies; the ordinary desktop workflow needs no separate Python.

From a development environment with the pinned application dependencies:

```console
python tools/read_regional_annotation.py "/path/to/immutable/checkpoint"
python tools/read_regional_annotation.py "/path/to/results.zip" --case-key SYNTHETIC_01
python tools/read_regional_annotation.py "/path/to/checkpoint" --source-image "/path/to/original/image.nii.gz"
```

Use a real exported case key locally when reading a private result. Without
`--case-key`, a ZIP must contain exactly one case. The optional source image is
read only; its bytes/hash and complete geometry must match saved provenance.
Without it, the reader checks outputs against the recorded source grid and does
not claim independently verified original MRI bytes.

The reader checks the manifest and every payload hash, source identity, fixed
whole/regional label mappings, full native dimensions/spacing/origin/direction,
active consistent qform/sform, mm units, integer storage, exact parent containment,
complete assigned/unassigned partition, review CSV/JSON consistency, attribution,
pending protocol and validity. ZIP entries are read by a fixed whitelist; arbitrary
ZIP paths are never extracted. Temporary local copies are removed on completion.

Python callers can use:

```python
from tools.read_regional_annotation import read_regional_annotation

loaded = read_regional_annotation(checkpoint_or_zip, case_key=None)
regions_kji = loaded["regions"]                  # unchanged values 0…8 for inspection
valid_kji = loaded["regional_validity"]          # currently zero everywhere
excluded_targets_kji = loaded["training_targets"]  # currently -1 everywhere
assert loaded["accepted_regional_voxels"] == 0
```

The `-1` value is an in-memory exclusion sentinel in this example, never a new
exported regional training class. Unassigned tissue (7/8), uncertainty, unreviewed
or flagged slices, practice work and protocol-pending assignments must not become
ordinary class-0/background or accepted anatomical targets. The current expert
regional protocol is pending, so **every regional voxel is excluded**, even if all
six regions are drawn and all software review flags are complete. Attempting to
edit metadata into an approved/released regional state fails validation. A future
accepted regional training route requires an agreed expert protocol, a separately
versioned contract, validation and real downstream-loader integration.

Exit code 0 means the saved files were technically read successfully. It does not
mean regional anatomy is approved or eligible for training. Invalid files produce
exit code 2 and an actionable message without a normal-interface stack trace.
