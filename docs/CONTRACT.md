# Input/output contract v1

Application 0.1.0. The preparation project defines the input schema. This application verifies it without changing the source files. Folder-layout revision 2 adds the flat naming below while keeping the earlier nested layout readable. Synthetic checks do not establish anatomical validity or Windows acceptance.

## Input adapter: `meniscus_case/1`

Choose a complete dataset root with `README.txt`, `case_index.csv`, and case folders:

```text
Cases/OAI_<participant_id>_M<visit_month, 3 digits>_<LEFT|RIGHT>/
    image.nii.gz
    case.json
    slice_review.csv
```

The earlier `Cases/OAI_<participant_id>/M<visit_month, 3 digits>/<LEFT|RIGHT>/series_<source_series_key>/` layout is also accepted. Its known empty `annotations/` directory may remain; it is ignored, and the application never writes annotations into the source package or auto-loads nearby masks. In both layouts the full folder name must match the ID, visit and side in unchanged `case.json`; the legacy series component must also match the original source key. Shorter folders never change case keys, series identifiers, dates, images or dataset identity. The index's `relative_folder` is the only index value changed by a folder-layout migration.

Draft checkpoints remain in the separate local work folder, and approved result exports remain in the separate results folder. Work binding hashes source metadata and image checksums, not source locations or folder layout, so an intact migrated package can reconnect existing work. A live loaded dataset must be closed and reopened after a migration: its in-memory source-file hash guards deliberately reject an index modified during the session.

The case index has exactly these ordered columns:

```text
participant_id,visit_month,knee_side,case_key,relative_folder,expected_slice_count,annotation_status,image_sha256
```

`case.json` is a closed schema with exactly these fields:

```text
schema_version dataset_version case_key participant_id visit_month
original_visit_code source_visit_label knee_side sequence source_series_key
series_instance_uid archive_series_number dicom_series_number source_study_date
source_series_description dimensions_xyz spacing_xyz_mm origin_lps_mm
direction_lps_columns expected_slice_count slice_index_convention image_sha256
annotation_status preparation_verifier
```

Required values include `schema_version = meniscus_case/1`, `sequence = sagittal IW fat-suppressed TSE`, explicit `knee_side = L|R`, and input `annotation_status = not_started`. `dimensions_xyz` are positive integer I,J,K counts. `spacing_xyz_mm` are positive native voxel spacings. `direction_lps_columns` is a 3×3 orthonormal matrix with direction vectors in its columns; `origin_lps_mm` is the I=J=K=0 voxel centre. Scanner-space directions and origins are retained. Only regular orthogonal acquired grids are supported; sheared, irregular or non-sagittal acquired grids are rejected.

The exact existing `slice_index_convention` string is:

> zero-based along physical volume axis 2; ascending projection on DICOM row-direction cross column-direction; never InstanceNumber

The input review table has columns `slice_index,status`, one ordered row per K index (0…N−1), initially `not_reviewed` for all slices. It is validated and then left untouched. Source review records never replace the reader's explicit review records in the work folder.

Case index identity, path identity, JSON identity, source SHA-256, dimensions, transforms and native geometry must agree. Both NIfTI-1 qform and sform must be active, spatial units explicitly millimetres, and maximum physical corner disagreement ≤0.01 mm. Unknown units, missing/conflicting transforms, shear, wrong source bytes or geometry block import/editing. Case identifiers and UIDs must be unique. The adapter deliberately does not display sampling, exposure, clinical findings or train/test metadata.

The dataset identity is a location-independent canonical SHA-256 of sorted `(case_key, case_identity)` entries; each case identity hashes its complete source `case.json`. Moving an unchanged complete package is supported. A matching filename alone cannot reconnect work. Source case metadata or image changes require a new dataset identity and separate work folder.

## Indexing and label semantics

The primary Slicer view uses native I/J axes and K acquired-plane centres. Displayed slice **n = K + 1**, so the reader sees 1…N. In-memory arrays supplied to the core are **K,J,I**; NIfTI files use **I,J,K**. Conversion is a transpose, never a geometric resample, crop, resize, flip or dropped-empty-slice operation. RAS affine is `diag(-1,-1,1,1) × LPS affine`.

Anatomical output values are fixed independently of Slicer segment order:

| Value | Meaning |
|---|---|
| 0 | Background candidate; interpretation requires review/validity records |
| 1 | Medial meniscus |
| 2 | Lateral meniscus |

Medial/lateral are mutually exclusive. Uncertainty is a separate binary overlay and may overlap either anatomy or candidate background. It is never an undocumented third training class. `validity.nii.gz = 1` only for reviewed, unflagged slices outside uncertainty; a zero anatomical voxel with validity zero is **not confirmed background**.

Current conservative uncertainty policy: resolve every uncertainty voxel and attention flag before either practice or research approval. No automatic anatomical rule resolves uncertainty. Empty slices require explicit review. Editing any affected slice invalidates that slice's review; the Slicer integration observes voxel changes, including undo/redo.

## Optional explicit job configuration: `meniscus_job/1`

Legacy MRI-only packages contain no prediction permission or released drawing protocol. They retain their former blank/practice behavior. A prepared correction package instead contains an explicit `correction_job.json`, with every case listed as `correction`; it must never rely on the unlisted-case blank default. The core accepts an explicit job dictionary, never an arbitrary nearby prediction discovered on disk:

```json
{
  "schema_version": "meniscus_job/1",
  "dataset_identity": "<verified dataset SHA-256>",
  "protocol": {"version": "<documented protocol version>", "status": "draft"},
  "cases": {
    "<case_key>": {
      "annotation_mode": "correction",
      "starting_mask": {
        "path": "Cases/OAI_<ID>_M000_LEFT/starting_mask.nii.gz",
        "sha256": "<expected bytes SHA-256>",
        "source": "<source provenance>",
        "version": "<prediction version>"
      }
    }
  }
}
```

Permitted annotation modes are `blank` and `correction`. Generic historical jobs may still list only some cases; correction-package validation requires exact membership and explicit correction mode for every input case. A relative starting-mask path is safely anchored to `Dataset.root`, never the process working directory. Explicit absolute paths remain supported for historical jobs. Resolution does not rewrite the job dictionary or its canonical hash, so moving an intact package does not break portable job/work bindings.

A correction mask must pass native-grid checks, integer 0/1/2 mapping and its expected hash. Its original bytes are preserved once in the separate local work folder and included with an approved correction export. Starting-mask source/version/hash and canonical job hash are recorded in annotations. Reloading work under changed initialization permissions is blocked, so an existing blank or differently configured work folder cannot silently become correction work. Choose a separate correction work folder when previous work used a different job.

The existing UI `Help → Annotation setup…` action (dialog title `Load explicit annotation job`) validates jobs through `load_job_config`. Opening a dataset with no remembered job and no fixed software-practice launcher automatically validates its explicit root `correction_job.json`; invalid or incomplete permissions raise an error instead of silently selecting blank annotation. Known starting-mask files without an explicit job also block import instead of falling back to blank. In an ordinary correction package, a remembered or newly selected job must likewise cover every case in correction mode, so stale blank/partial settings cannot override package intent. Fixed software-practice launchers retain their explicitly scoped actor/job configuration. No new interface design is required for this adapter.

Some existing predictions cannot establish the requested categorical source labels. An explicitly blocked case can remain visible in the unchanged MRI cohort using this narrow extension:

```json
{"annotation_mode":"correction", "availability":"unresolved", "reason":"<specific technical reason>", "starting_mask":null}
```

Such a rule never becomes blank. Opening it is rejected before a case work folder or label array is created. Ready cases in the same job remain usable. Read-only `validate_job(..., require_full_correction=True)` rejects any unresolved case by default; explicit `allow_unresolved=True` returns the ready/unresolved counts and `correction_package_complete=false`. Structurally valid partial preparation must not be called a complete correction dataset.

Run `tools/check_correction_inputs.py --dataset PACKAGE --output PRIVATE_REPORT` for the application input route without editing or approving annotations. Use `--allow-unresolved` only when recording a documented partial package; it does not resolve the missing input.

The protocol status is `draft|released`; version is required. Draft protocol permits only distinctly marked practice approval. A released anatomical protocol must be supplied explicitly by the responsible research team; the application does not invent drawing rules or independently certify that a protocol is suitable.

## Local work: `meniscus_work/1`

The UI resolves Documents through Qt/OS. Suggested root is `Documents/Meniscus_annotation_work/<dataset_version>/`; the selected local location is remembered. It must be separate from the source and outside recognized live Dropbox/CloudStorage/OneDrive locations. Work is never written into source `annotations/`. Other sync providers cannot all be detected by path text; use a genuinely local folder.

```text
<work root>/
    dataset.json
    cases/<24-character case-key hash>/
        case.lock
        CURRENT.json
        starting-mask-<sha256>.nii.gz   # correction only
        versions/
            v-<UTC timestamp>-<unique suffix>/
                segmentation.seg.nrrd
                labels.nii.gz
                uncertainty.nii.gz
                validity.nii.gz
                slice_review.csv
                annotation.json
                manifest.json
```

Every save creates a new immutable checkpoint directory. Files are written into a hidden `.pending-*` directory, reopened and checked, fsynced, and atomically renamed on the same filesystem. `CURRENT.json` is an atomically replaced convenience pointer. Recovery scans complete version directories; `.pending-*` directories are never resumed. If the latest saved version is corrupt, the newest intact prior version is recovered and the UI reports recovery. If no intact version remains, editing is blocked and a backup must be restored. OS-held per-case locks prevent concurrent writers and release on process death; lock files persist safely. Undo/redo is an in-memory Slicer facility, not an across-restart history.

`annotation.json` (`meniscus_annotation/1`) records source identity and metadata, app version, fixed mapping, initialization provenance, protocol, the reader's role, review rows, compartments considered, case/slice notes, position, state and approval. `slice_review.csv` has ordered fields `slice_index,displayed_slice,status,attention_flag,note`. Review and attention are separate. `manifest.json` (`meniscus_checkpoint/1`) records source hash, case identity and SHA-256 for all six base payload files, plus the five regional files when the optional versioned regional extension is present. `manifest.json` does not recursively hash itself; its hash is included in exported results metadata.

Each NIfTI output is full native extent, uint8, mm units, with consistent active qform/sform. Outputs are reopened independently with nibabel and compared voxel-for-voxel with arrays supplied by Slicer. The editable segmentation writer is Slicer's own writer; actual segmentation reopening is exercised by the Slicer integration tests separately from the core tests.

Approving requires complete explicit review, both compartments considered, annotator/protocol metadata, no unresolved uncertainty/attention, valid outputs, and a deliberate UI action. The explicitly selected reader is the annotator **and** approver; this is not an independent second-reader assessment. Editing an approved version saves a new draft, preserving the previous approved directory.

## Export: `meniscus_results/1`

`Export approved cases` creates an atomically completed timestamped ZIP in a separate results folder, suggested `Documents/Meniscus_annotation_results/`. MRI images are omitted. All selected eligible cases, their approved checkpoint files, review/approval metadata and original starting mask if used are included. Case folders use a deterministic case-key hash; `results.json` maps folders to full case identities and approved checkpoint IDs. All-case export skips cases without approval. Explicit selection containing an unapproved case is rejected with a case-specific action. If later draft edits exist, export uses the preserved approved checkpoint, identified in results metadata; draft content is never presented as approved.

Practice exports require an explicit `include_practice=True` choice and are named `PRACTICE_ONLY-Meniscus_results_…zip`, with practice status in results metadata and README. Routine research export includes only research approvals. Fixed mapping and `validity.nii.gz` semantics travel with the ZIP. Outputs contain no unnecessary source MRI duplication, private selection/exposure records or preparation logs.

Technical acceptance establishes identity, geometry, byte integrity, file consistency, mapping and review completeness. It does **not** prove anatomical correctness, internally shifted drawing correctness, reader independence, downstream loader compatibility or readiness for training. The real downstream training-loader check remains an explicit integration requirement until its loader is available and exercised.


## Explicit software-practice context (optional job extension)

A `meniscus_job/1` may include this versioned-contract extension when software
checks or an unverified preview operator use real or synthetic practice images:

```json
"practice_context": {
  "purpose": "software_practice",
  "actor": "Software QA (automated)",
  "actor_type": "automated"
}
```

The only actor types and canonical role labels are `automated` /
`Software QA (automated)` and `human_unverified` /
`Preview user (identity unverified)`. The three context fields are explicit and
closed. Software practice must use a draft protocol. Its immutable context is
bound in the local `dataset.json` and every saved annotation; a work folder cannot
be reused for ordinary production work or a different practice actor. Work and
results must still be separate from source inputs and from each other.

Software-practice metadata records `annotation_purpose = software_practice`, the
canonical actor as annotator, and no approver while draft. A workflow completion
may be saved only with explicit practice approval. Automated completion records
`approval_type = automated_software_check`, the software actor as approver,
`human_anatomical_approval = false`, `accepted_research_annotation = false` and
`deliberate_approval_required_by_ui = false`. It never implies that a research reader reviewed
or approved an automated drawing. Manual unverified preview completion uses
`manual_software_practice`, the preview role label and the UI-confirmation
requirement, while remaining explicitly outside research acceptance. Existing
review, uncertainty, compartment, source-identity and technical export safeguards
remain required in both modes.

Software-practice exports require the explicit practice option. Their filenames
begin `SOFTWARE_PRACTICE_ONLY-`; results metadata and README state that these are
not accepted research annotations or human anatomical approvals. They cannot
appear in ordinary research exports. The source MRI is omitted. Source identities
and actor/context remain recorded in each private case annotation.

Jobs without `practice_context` require an explicit reader identity. A named job
uses its recorded assignment. An unassigned job uses a local reader binding
without changing the shared job or resolution registry. Older saved annotations
retain their original attribution; they can be reopened only with a matching
explicitly selected reader and the original input bindings. Ordinary draft-protocol practice exports
retain their existing `PRACTICE_ONLY-` prefix.


For explicit `software_practice` contexts, **every voxel of `validity.nii.gz` is
zero**, for automated QA and unverified manual practice alike. Programmatically
completed review rows or practice approval never turn raw labels or zero-valued
background into anatomically confirmed training targets. The full-grid 0/1/2
label image remains available only to test software geometry, mapping and save/
export behaviour. Checkpoint validation recomputes this full exclusion and rejects
a software-practice validity image that grants any voxel training validity.
Ordinary production and ordinary draft-protocol practice without this explicit
context keep their existing review/flag/uncertainty-based validity semantics.

## Local reader assignments

Ordinary jobs with no `annotator` do not supply a default person's name. Before
creating work, the interface requires a reader name or study ID. The local work
folder stores `reader_assignment.json` with schema `meniscus_reader_assignment/1`,
the dataset identity, original base job identity, and selected reader. Neither
the shared job nor its additive correction resolutions are rewritten. Reader
identity is self-reported; this is attribution, not authentication.

The default work folder and remembered location are separated by the explicit
reader and original job. New annotations and approvals record that reader; the
local binding is checked when opening, saving, and exporting. Reader names never
become raw filesystem path components. Explicit named jobs and software-practice
roles retain their existing assignment rules.

Legacy checkpoints are not relabelled. Reconnecting an older work folder requires
the explicitly selected reader to match the recorded attribution and original
job/dataset bindings. Unmatched or unverifiable work is preserved and refused.


## Optional regional extension

The whole-meniscus input/job, label mapping and historical checkpoints stay
unchanged. New regional work uses [meniscus_regions/1](REGIONAL_CONTRACT.md) and
`meniscus_regional_extension/1`: six named regions plus explicit unassigned
medial/lateral tissue (7/8) on the same complete native grid. Regional metadata,
review, uncertainty, validity and protocol provenance are separate. Merely opening
a whole-only checkpoint creates no replacement file or new job identity.

An extended checkpoint may preserve an unchanged whole approval alongside a
clearly marked regional draft. This exception requires exact whole arrays and
protected primary metadata matching the saved approval. Any primary change
follows the existing new-draft rules. Export explicitly records the regional
draft/pending status; it never represents that draft as regional approval. The
regional protocol is pending, research approval is unavailable and regional
validity is zero throughout. See [the loading example](REGIONAL_READER.md); no
actual downstream training pipeline has been integrated.
