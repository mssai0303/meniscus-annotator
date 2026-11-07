# Validation record — development version 0.1.0

The focused application runs in the actual pinned Slicer desktop runtime. Mac
verification uses **Intel Slicer 5.12.4 under Rosetta on Apple Silicon**, not a
native ARM runtime. Technical checks establish file integrity, native geometry
and software behaviour; they do not establish anatomical correctness, accepted
research annotations or readiness for the full annotation batch.

## Executed checks and their scope

### Correction pilot repairs — 7 November 2026

The Export dialog previously had no usable buttons despite direct-function
export tests passing. That distinction is now tested explicitly. Actual Mac
Slicer modal interactions passed 19 checks: visible controls, Cancel/Escape,
Export/Return, selected-only ZIP contents, unchanged synthetic inputs and
blank-start/reader confirmations defaulting to No. These are automated Qt
events, not a human usability test; the native export folder picker is excluded.

The scoped application, adapter and packaging suite passed 187 tests. A prepared
Windows test-kit correction workflow was exercised on Mac/Rosetta with 33
checks and 16 fresh-process restoration checks. The maintained synthetic blank
workflow also passed 182 checks and 7 restoration checks using an explicit
software-practice actor. Build identity was checked independently on five
synthetic receipt scenarios. These counts describe overlapping test scopes and
must not be added as independent validation.

No new real MRI was opened during these repairs. Windows package construction,
hosted integration and interactive Horizon acceptance must each have their own
receipt before being claimed complete. Historical tests below retain their
original scope; direct-function export tests did not cover the broken dialog.

### Earlier development evidence

| Route | Result | Scope |
| --- | --- | --- |
| Application core and practice-context tests | 70 passed | Existing annotation behaviour and explicit practice-role isolation |
| Layout, migration and apply tests | 55 passed | App/adapter source identity, both layouts and saved-work continuity |
| Correction-job tests | 26 passed | Relative permissions, complete job coverage, relocation and unresolved-case blocking |
| Redesigned synthetic native workflow | 182 assertions per run passed | Actual Slicer editing, navigation, saving, approval/export and source preservation |
| Fresh-process synthetic restore | 7 assertions passed | Case, slice, notes, masks and controls after restart |
| Direct bootstrap startup | 5 assertions passed | Focused workspace without test-driven module selection |
| Initial permitted two-scan practice workflow | 318 checks passed | Actual Mac application on the two permitted complete scans |
| Initial practice restore | 36 checks passed | Reopening the saved practice work |
| Targeted checks after superior-up display correction | 203 checks passed | Acquired-plane display, interaction and saved-grid behaviour on the permitted scans |
| Post-correction practice restore | 36 checks passed | Restoring the post-correction practice state |
| Final practice status | 27/27 passed | Final status covering both permitted scans |
| Existing-mask correction module workflow | 337 passed | Both permitted real scans, native existing-label erase/undo, Draw/Paint, review, save and export |
| Correction fresh-process restore | 45 passed | Last case arrays, native geometry, original prediction and provenance |
| Baseline correction cold restore | 65 passed | Separate process; exact baseline export arrays, geometry and original provenance; no new checkpoint |
| Initial correction package input check | 249 verified; 1 unresolved at that check | Historical receipt before the separate case-resolution update described below |
| Hosted Windows installer lifecycle | Passed | Installation, hashes, runtime imports, duplicate-install/locked-runtime guards and safe uninstall |
| Redesigned Windows application acceptance | Paused; incomplete | No full acceptance claim |

The app/adapter total is **151 tests**. Broad collection of separate preparation
tool tests could not run in the lean app environment because pydicom/SimpleITK
were absent there; no preparation code or dependencies were changed, and no
complete preparation-suite pass is claimed. The Slicer runtime includes its own
SimpleITK for native saved-file checks.

The practice runs above overlap in coverage and must not be added into a single
count. The later targeted checks verify the superior-up display correction; the
earlier synthetic records remain identified by their own receipts and hashes.
Raw synthetic-only receipts and screenshots are in [evidence/](evidence/).
**Real MRI images, identities, private filenames, reports and logs remain outside
Git.** Committed screenshots use synthetic inputs only.

## Software-practice safeguards

The two permitted scans are used in an explicitly configured SOFTWARE PRACTICE
workspace with separate local work and results. Automated and manual practice
have canonical software actors; automated tests are never attributed to a research reader.
Every validity voxel remains **zero**, including after software review/approval.
Neither labelled voxels nor background are accepted research training targets.
These checks are software and geometry verification, not an anatomical assessment
or independent second-reader approval.

A subsequent manual launch of the current code was confirmed ready. Its upright
image was visually inspected and saved practice state was restored. Already-open
windows do not update their loaded code automatically: save and close normally,
then relaunch to load a change. No claim relies on silently restarting an older
manual window.

## Native editing and output checks

The synthetic workflow drives native Paint, Erase and Draw through view events.
It checks each acquired plane and the 1..N slider/readout, first/last-slice edits,
oblique single-slice isolation, label replacement, uncertainty overlap,
Undo/Redo, review invalidation, empty-mask save/reopen and correction initialization.
It also checks notes typing without shortcuts, orientation-only secondary views,
failed-save/load recovery, writer locks, immutable approvals and approved export.

The acquired-plane view is now superior-up. Display fitting and Reset view retain
the requested acquired slice; neither the source grid nor exported arrays are
reoriented, resampled or cropped. Independent saved-file readers compare voxels,
complete extents, spacing, origin and direction. Technical acceptance also checks
spatial units, qform/sform consistency, integer label values, fixed medial/lateral
mapping, uncertainty/validity records and hashes. Editable segmentations reopen
against the original reference grid. Source files remain unchanged.

Correction tests compare initial in-app arrays with the exact explicitly permitted
nonzero mask, erase existing voxels from each compartment on the intended acquired
slice, and compare exact arrays after Undo/Redo. Saved/exported original prediction
bytes retain their source/version/SHA provenance. All 1,252 then-current package files
matched the post-addition source manifest after testing; original 750 case files
and index also matched the earlier immutable pre-addition receipt. These checks
do not accept the predictions anatomically. At that check one unresolved source
mask remained blocked; it was never replaced by blank annotation. The subsequent
documented case resolution is a separate update, not part of that old receipt.

**Draw** closes point-to-point clicks into a filled polygon on the current acquired
slice; Paint/Erase provide touch-ups. To adjust brightness/contrast choose
**Display and orientation → Window/level**, then left-drag. Right-drag zooms.
The explicit window/level interaction replaces the earlier incorrect right-drag
instruction. Choosing a drawing tool restores annotation interaction mode.

Actual synthetic captures at 1280×800 and 1440×900 logical pixels were inspected
on Retina 2×. This is separate from Windows display scaling. Existing nonfatal
Slicer subject-hierarchy warnings occurred during temporary-node cleanup; the
reported assertions and repeated-save scene-node checks passed.

## Windows status

On Windows 10 Enterprise build 19045 x64 Horizon, the user reported successful
normal-user write/readback and checksum persistence through disconnect/reconnect
and sign-out/new login. The official pinned Slicer runtime opened; the synthetic
saved-volume checks passed and reported NVIDIA A16-1Q with an OpenGL 3.2 context.
The user confirmed the grayscale image display. This baseline probe was ordinary
Slicer and does not establish acceptance of the redesigned annotation application.
Explicit scrolling/full application acceptance remains incomplete. The correction
installer has been built and published as a test candidate; hosted installer
lifecycle checks are not interactive GUI acceptance.

Windows 11 remains **untested**, not declared incompatible. No paid VM or large
source build is required before completing available Windows 10 compatibility
checks. Windows 100%, 125%, 150% and 200% scaling, offline installed operation,
spaces/Unicode and supported path lengths still need their applicable checks.

## Responsibilities and remaining gates

`MeniscusAnnotatorLib/core.py` is the maintained application output acceptance
route; `tools/check_work.py` delegates to it. Input preparation remains a separate
responsibility. Selection/exposure audits were not repeated or included in the
reader interface.

The real input package is prepared with flat case folders, and legacy layout
support is retained. Two permitted practice scans have now been exercised in the
Mac app, but this does not accept the full research batch. A released anatomical
protocol, actual expert annotation/review, the final installed Windows workflow
and downstream training-loader integration remain separate requirements.
The actual downstream loader was not available and has not passed integration.
Geometry checks cannot detect every internally shifted or incorrectly drawn mask.

## Offline reader delivery update — 7 November 2026

The primary desktop acceptance target is the available Windows 10 Enterprise
x64 Horizon desktop. Windows 11 remains untested. The reader installer bundles
the runtime/dependencies and an offline HTML guide. Its Start menu exposes only
the application, reader guide and uninstaller. Internal maintainer diagnostics
are not part of the doctor's correction workflow.

The actual Mac Slicer Export/dialog regression passed 26 checks after named-reader
work location separation. Two synthetic named assignments with the same dataset
used different remembered work folders through the ordinary Open dataset route
(no forced work_root); switching readers preserved the first reader's saved note,
attribution and checkpoint bytes. Old shared preferences were not reused. Export,
Cancel, Return and Escape checks remained passing. These are automated native
Qt events, not a human usability test or Windows acceptance. The visible reader
caption was inspected in the native window capture.

Named assignments use the original job hash for their work location. Additive
case resolutions retain that location. Legacy and software-practice locations
remain unchanged. Existing named jobs saved by earlier preview builds may need
the coordinator to reconnect their original work folder explicitly; no old
checkpoints are moved, relabelled or discarded.

## Windows test candidate 2 and completed input preparation

The source `cb5919bea6a69e26d2396b509d9f2dad71f8cc68` installer is available as
[Windows test candidate 2](https://github.com/mssai0303/meniscus-annotator/releases/tag/v0.1.0-windows-correction-test.2).
Its SHA-256 is `d09b4898dadbf328eac86c6857ad7f2072106a4b03de70bedfee1e18179bb5f6`.
[Build 42394913240](https://github.com/mssai0303/meniscus-annotator/actions/runs/42394913240)
passed installed payload integrity, source/runtime identity, synthetic package
generation, duplicate-install protection, locked-runtime uninstall protection
and safe uninstall. The local contract suite passed 226 tests. Desktop editing,
restart and export checks were explicitly NOT RUN on the hosted runner because
of its graphics limitation. Actual Windows 10 acceptance remains pending.

The dataset preparation handoff now reports all 250 starting masks technically
prepared. The previously blocked case uses the separately documented additive
resolution contract; the original job and the other cases' bindings remain
unchanged. This source includes that contract. The predictions remain unreviewed
automated starting points; the package update is not expert approval or a new
independent image review by this application-maintenance task.
