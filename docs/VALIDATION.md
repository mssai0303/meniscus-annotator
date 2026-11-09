# Validation record — 0.2.0 repaired review candidate

The focused application runs in the actual pinned Slicer desktop runtime. Mac
verification uses **Intel Slicer 5.12.4 under Rosetta on Apple Silicon**, not a
native ARM runtime. Technical checks establish file integrity, native geometry
and software behaviour; they do not establish anatomical correctness, accepted
research annotations or readiness for the full annotation batch.

## Current repaired review candidate

Application source `60e5a33`, tag `v0.2.0-review-repair.3`, fingerprint
`f886293c7a8c8a0e4029f792ab6c8aa23c2d8cdaebf6bd50874602c86d398848`.
The [finding-by-finding record](REVIEW_REPAIRS.md) distinguishes repairs from
conditional risks, alternative design handling and remaining platform gaps.

The latest Mac interface passes 224 ordinary visible-workflow checks and 21
fresh-process checks, plus 66 fault-injection checks for failed Save/review and
retry. These use actual Qt controls/native VTK effects with injected events and
Qt button activation, not human or OS-pointer acceptance. Geometry testing adds
130 orientation, 1,019 eight-grid Draw and 172 restart checks. Legacy whole-only
and regional reader fixtures pass 38/39 checks; crash-journal write/recovery
passes 44/26. Two isolated authorized real practice copies pass 367/28 workflow
and restart checks, independent ZIP/native-grid inspection and unchanged source
hashes. Actual old human-practice work validates read-only with all checkpoint
and binding bytes preserved. No new doctor or anatomical reference was created.

Four Mac Qt simulations (100/125/150/175%) pass 297 overlapping checks each,
including small-window scroll reachability, fixed footer actions and keyboard
Undo. At 200% this Mac's 756×439 available logical desktop is below the 800×480
minimum; desktop layout acceptance is not claimed. Larger requested windows
sometimes hit OS limits. These are not native Windows DPI checks.

Final [Windows CI 42559454615](https://github.com/mssai0303/meniscus-annotator/actions/runs/42559454615)
on Server 2025 x64 build 26100 passes 354 portable tests, installation/imports,
55 actual installed headless persistence/export checks, installation safeguards,
uninstall/reinstall and independent extraction/hash verification of all 9,603
payload files. Fresh ANGLE context creation fails before image rendering; strict
offline isolation is unavailable under hosted policy. Revised Windows GUI/DPI,
Windows 10 interactive acceptance and Windows 11 remain unverified. Earlier
Horizon success applies to the earlier build. No repeat Horizon test is requested.
See the [Windows receipt](../packaging/evidence/windows-review-repair-ci.json).

Mac uses Intel Slicer 5.12.4 revision 4e21c19 through Rosetta on Apple Silicon
(macOS 27.2 build 26B123), not native ARM. The new preview has a separate frozen
application/profile/work folder and remains open with a real oblique practice
scan. Earlier windows are preserved. Its launcher depends on the existing pinned
runtime, checks its availability and does not download or change security settings;
a standalone Mac installer is not supplied.

The six-page Word guide was rendered and every page inspected. It identifies this
as a repaired review candidate. Regional definitions/research approval/training
validity remain pending/blocked/zero; reviewed-voxel validity never establishes
practice eligibility for research. Technical checks do not establish anatomy or
readiness for the complete 250-case batch.

The following 0.1.0 records are historical and do not replace the current evidence.

## Executed checks and their scope

### Dropbox review delivery — 8 November 2026

At the user's request, the shared Windows software folder was updated with the
review installer built from `b575000` and the five-page Word guide. The installer
SHA-256 is `daf4845a3ec51e9ea3d824bc8e71aed0abaa4aaadc45ee992d2808da7845e617`.
Both previous delivery files were backed up outside the shared folder. No dataset,
starting-mask, protocol or annotation files were changed by this delivery.

The Word guide now describes complete meniscal coverage as the intended target
of the Whole meniscus task, not an established property of the unreviewed
predictions. All five corrected pages were rendered and inspected. Its SHA-256
is `8b54f606789624ebaf807cc75185087495a6b7a8119d4f93e53fddde93c4f210`.
This wording-only DOCX change does not change the installer or application code.

Delivery is for reviewer evaluation. The Windows installation/runtime checks
below passed, while revised native Windows GUI, DPI and strict offline acceptance
remain unverified. Regional research approval remains blocked pending an expert
protocol. Distribution does not change those validation limits.

### Visual and regional review 1 — 8 November 2026

Source/tag: `b5750000436b935d24993e2690ed0ad29ecd4882` /
`v0.1.0-visual-regions-review.1`. Main SHA-256 is
`34e4be300d5a2ba80c1477a65b59735694472269e04cd4ded5c0384c79629fc4`;
combined application fingerprint is
`897372b05d751f8d53e9f292fcbd9aa5c766dd0a74962698225362004f6547ff`.
All following Mac checks use this final source, after fixing the excessive
pending-contour footer and expanded-panel clipping.

| Route | Passed checks | Scope |
| --- | ---: | --- |
| Portable application/adapter/packaging | 315 | Includes 47 new regional tests |
| Native whole-meniscus workflow / separate restart | 991 / 172 | Eight left/right × physical stack direction × regular/oblique fixtures |
| Native regional workflow / separate restart | 971 / 205 | Parent-restricted Draw/Paint/Erase, exact ten-segment Undo/Redo, assessments, review, source/native-grid export |
| Independent whole-only legacy fixture | 33 | Unchanged six-file checkpoint retained; first regional save adds a new immutable version |
| Actual Mac layout/scaling and cold preferences | 1,036 | Four actual Qt DPR simulations; normal/pending/collapsed/expanded states |
| Two isolated real practice scans, whole / restart | 274 / 91 | Full acquired stacks, actual controls, unchanged original predictions and sources |
| Same two practice scans, regional / restart | 116 / 52 | Assign/change/erase regions, uncertainty/absence, separate reviews/approval, full-grid export |
| Existing human-unverified saved work | 124 | Exact old arrays, attribution, notes/review and all four checkpoints preserved |
| Standalone regional reader | 2 cases | Final exported ZIP/source checks; every regional target correctly excluded |

These scopes overlap. They are automated native Qt/VTK interactions and visual
inspection, not independent clinical validations. Real probes used automated
software-practice attribution and isolated work. No anatomical reference or Jeff
approval was created. Original source checks covered the two permitted scans and
shared metadata; no broad cohort audit was repeated. Earlier practice files also
matched their frozen hashes after testing.

The application now distinguishes the whole task from regional assignment. Native
editor masks restrict region edits to the selected parent; whole-mask changes
remove incompatible assignments and invalidate affected regional reviews. Values
7/8 explicitly retain unassigned medial/lateral tissue. Regional research approval
is unavailable while expert horn/body definitions are pending; regional validity
is zero throughout, including after whole approval. The reader example is not
integration with a downstream training pipeline.

The compact header/footer measure 55/95 logical pixels in the recorded Mac runs.
The footer remains compact with Finish/Discard present. Expanded CTK panels fit
their viewport with a vertical scrollbar and no essential horizontal clipping.
Actual 1280×800 and 1024×640 were achieved. The 1440×900 request was achieved at
DPR 1 and 1.5; fractional rounding and the DPR 2 available-height limit (847) are
recorded. Ordinary controls resolve to native Mac 11 pt regular; restricted
headings request semibold but this runtime resolves them to bold. These Qt DPR
simulations are not Windows operating-system DPI acceptance. The updated five-page
Word guide was rendered and every page inspected.

The separate Mac preview is open with a real practice scan, Draw selected,
Regions initially Not assigned, and no automated QA marks or approvals. Its
launcher/profile/work are separate from all earlier previews. Source data,
correction jobs and the shared installer remain unchanged.

The tagged Windows x64 candidate is built separately in
[CI 42529049659](https://github.com/mssai0303/meniscus-annotator/actions/runs/42529049659).
On Windows Server 2025 x64 build 26100, all 315 portable tests and actual
installation, payload hashes, runtime imports, regional helper initialization,
optional reader import, generation and uninstall safeguards passed. All three
guide figures, both regional documents and the reader example were independently
extracted from the actual installer and matched source/manifest hashes. The
installed application fingerprint matches this Mac source.

Native GUI workflows remain blocked: the host supplied actual OpenGL 3.0 and
black canvas pixels, below 3.2. Regional editing/restart/legacy, Draw, export and
scaling were not passed. Strict offline isolation also remains unverified because
host policy did not fully enforce the outbound rules. See
[the Windows receipt](../packaging/evidence/windows-visual-regions-review-ci.json).
Mac tests and earlier Windows 10 success do not establish this revision's native
Windows interaction acceptance. Windows 11 remains untested. No new user-run
Horizon session is requested.

The [generic review receipt](evidence/visual-regional-review-20261108.json) contains
source/image hashes and platform scope. Private MRI evidence remains outside Git.


### Draw-first revision — 8 November 2026

Tested application file SHA-256:
`ce91cebdecb7e2a412815b673159534cff5b1b47f5cf2a3d9b127c1b0e24dbfc`.
The storage/validation core and saved-file schema were not changed.

| Route | Actual result | Scope |
| --- | --- | --- |
| Pure application/adapter/packaging checks | 268 passed | Synthetic source/job/checkpoint and installer assembly logic |
| Actual Mac native Draw matrix | 983 passed | Left/right × both physical acquisition directions × regular/oblique; actual Draw, Erase, Undo/Redo, Save and Export controls |
| Fresh-process synthetic restoration | 172 passed | All eight cases, exact arrays/NRRD and physical grid/frame basis |
| Actual isolated real-case workflow | 274 passed | Same two authorized practice scans; actual Export menu/modal and all acquired slices |
| Real-case cold restoration | 91 passed | Both cases, arrays, notes/review, source identity, displayed slice and geometry |
| Focused real oblique point continuation | 22 passed | Four points with zoom/pan; existing RAS points and voxels unchanged |
| Existing saved-work compatibility | 124 passed | One previous blank-practice case and all four immutable checkpoints; original/copied work bytes unchanged |
| Clean real default capture | 20 passed | Original prediction only, Draw default, no test marks/review/approval/checkpoint |
| Mac Qt DPR layout simulations | 90 per DPR passed | Actual DPR 1, 1.25, 1.5 and 2; controls, ancestor viewports and pending footer |

Native Draw allowed an unfinished contour to survive a target change. The focused
workspace now blocks slice, label, tool, case, save, review and normal-close
transitions until the contour is finished or explicitly discarded. Right-drag
retains the contour. A transformed source is blocked before native fill. Separate
display-only point glyphs do not enter the native contour rasterization data.

The real oblique scan exposed an additional floating-point issue: redundant
same-plane reprojection changed the offset by roughly 7e-15 mm, and native Draw
uses exact offset equality when accepting another point. The fix avoids redundant
reprojection on an already verified acquired plane. It does not move existing
RAS points, change native Draw metadata, resample images or alter label geometry.
The subsequent synthetic matrix includes Modified/zoom/pan/point-continuation
regressions on every oblique case.

Real tests use fresh automated software-practice work. The old work compatibility
test copies existing work and preserves its historical actor rather than
performing automated drawing under that identity. All practice validity remains
zero and approvals are explicitly software-only. Scoped original/copy hashes
matched; no broad cohort or dataset audit was repeated. These are automated
native Qt/VTK interactions plus visual inspection, not expert anatomical review.

Actual laptop-size layout checks include default and expanded secondary panels,
ancestor-viewport clipping, pending-contour controls and all Save/review actions.
Exact 1280×800 and 1366×768 client sizes were achieved. Fractional scales can
round a dimension by one pixel; the receipts record actual sizes, screen limits
and device pixel ratios. A separate settled normal-window trace confirmed no
contour-induced window growth. Initial native Slicer fullscreen preferences were
isolated from the Mac preview. The four-page Word guide was rendered and every
page visually inspected. A generic [summary receipt](evidence/draw-workflow-review-20261108.json)
records these scopes; detailed real-data evidence remains private.
Calibrated Mac Qt device-pixel-ratio checks are recorded separately from native
Windows operating-system scaling or human interaction acceptance. Revised Windows
build/runtime/workflow results require their own dated receipt; earlier Windows
success does not establish this revision's acceptance. The shared installer is
not replaced by this review build.

The final Windows review candidate is built from `ed3aa91` / tag
`v0.1.0-zhang-review.4` in [CI 42496348555](https://github.com/mssai0303/meniscus-annotator/actions/runs/42496348555).
On **Windows Server 2025 x64 build 26100**, all 268 portable tests and fresh
installation, payload hashes, native runtime imports, synthetic generation,
duplicate-install, locked-uninstall and safe-uninstall checks passed. Installed
application bytes match the reviewed Mac bytes. Both guide figures and their
references were independently verified inside the actual installer.

This is **not** a passing Windows graphical workflow: the system renderer failed;
the two trusted bundled-software attempts supplied actual OpenGL 3.0 and a black
canvas, below the required 3.2. Native Draw, restart, export and scaling remain
blocked. No version/capability was spoofed, and test aliases were removed with
original installed hashes retained. Strict offline verification is also pending
because host policy could not fully enforce isolation. New-revision interactive
Windows 10 and Windows 11 checks remain unverified; no further user-run Horizon
session is requested. The prior successful Windows test retains its earlier
build scope. See the [generic Windows receipt](../packaging/evidence/windows-zhang-review-ci.json).

The first expanded Windows precheck found a portable-path inventory mismatch in
the maintenance migration/apply tools. Four path serialization calls now use
POSIX separators consistently with the schema; all 268 tests subsequently passed
on Windows. No real dataset migration or case-file operation was performed.
Python source uses LF on both platforms for stable build fingerprints.

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
