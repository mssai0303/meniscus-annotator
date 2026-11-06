# Validation record — development version 0.1.0

The focused application runs in the pinned **actual Slicer desktop runtime**.
It is not a browser viewer or a screenshot mock-up. These results establish
synthetic technical behaviour only. They do not establish anatomical correctness,
acceptance of a real dataset, or Windows readiness.

## Executed

| Route | Environment | Result |
| --- | --- | --- |
| Core synthetic checks | Apple Silicon Mac, Python3.9.6, NumPy1.26.4, nibabel5.3.2, pytest8.3.5 |47 passed |
| Actual Slicer workflow | macOS27.2, Slicer5.12.4 r34645/4e21c19, Intel runtime under Rosetta, Python3.12.10, NumPy2.4.6, nibabel5.3.2, SimpleITK2.5.5 |142 assertions passed |
| Fresh Slicer process resume | Same runtime; previous process closed through real window.close() |4 assertions passed |
| Maintained checkpoint checker | Reopened synthetic work from actual Slicer run |Passed |
| Windows 10 Horizon installation or interaction | Proposed Enterprise19045 x64 desktop; session access pending |Not run |

Raw synthetic-only receipts are committed in [evidence/](evidence/). The actual
application screenshot in [Jeff's guide](USER_GUIDE.md) was inspected at1280×800
logical pixels on Retina2×. A second requested1600×1000 capture was constrained
by the Mac desktop (actual dimensions are recorded in the receipt); it must not be described as a1600×1000 test.
Windows100/125/150/200% display scaling remains pending.

The native editor tests drive VTK mouse events through Paint, Erase and Draw.
They verify every acquired plane's indexing, known voxel locations and single-
acquired-slice changes on axis-aligned and oblique scans with different shapes,
17/23 slices and anisotropic spacing. They check label replacement and exact
undo/redo, independent uncertainty overlapping anatomy, preservation of that
uncertainty during anatomy edits, and review invalidation after edits.

The complete sequence exercises load, edit, explicit review/advance, save,
reopen, practice approval, a new draft after approval and export. Approval tests
set synthetic consideration/review states programmatically and invoke the same
save/approval implementation used by the confirmation UI; they are not Jeff's
anatomical assessment. The real protocol remains draft by default.

Saved NIfTI arrays and geometry are reopened with independent **SimpleITK** and
compared to in-memory arrays; the nibabel writer/checker also checks qform/sform,
spatial units, full extent and fixed integer labels. Editable .seg.nrrd files are
reopened through Slicer storage and all three fixed segment IDs compared to the
source-reference arrays. Exported approved voxels match the preserved approved
checkpoint even after a later draft. ZIP CRC and payload hashes pass. Every
source package file remains byte-for-byte unchanged.

Additional application tests exercise secondary-reformat editing rejection,
notes typing without drawing/navigation shortcuts, pending-stroke flush before
immediate close, save failure blocking a case switch, failed native volume load
releasing the lock, repeated saves without MRML node-count growth, and actual
window-close save plus fresh-process restoration of case/slice/notes/masks.
Nonfatal Slicer subject-hierarchy warnings occurred during temporary node cleanup;
all checks passed, including stable scene node count during repeated saves.

Core fault tests additionally cover corrupt-newest recovery, interrupted writes
before/after directory commit, disk-space/permission errors, operating-system
locks released after abrupt process exit, wrong/changed sources, absent/conflicting
transforms, unknown units, invalid/cropped labels, metadata/hash mismatches,
unsafe/symlink paths, explicit permitted correction and forbidden predictions.
Core-only tests use a labelled synthetic writer marker; they do not claim to
validate Slicer storage independently of the actual desktop tests above.

## Maintained responsibilities

`MeniscusAnnotatorLib/core.py` is the application output acceptance route.
`tools/check_work.py` delegates to that same implementation; it is not a forked
validator. The preparation workspace's current input contract/checker was read
for the native grid/schema. Historical unfinished checkers were not reused as
an acceptance route. No selection, exposure or research partition audit was
repeated or included in the interface.

The actual downstream training loader was not available and has **not** passed
integration. Before training, its owner must verify native geometry, class
mapping and validity/uncertainty semantics using accepted exported examples.
Geometry tests cannot detect every internally shifted or incorrectly drawn mask.

## Release gates still open

1. Build/package the Windows application and first check installation permissions,
   session persistence and synthetic rendering on the proposed Windows10 Enterprise
   build19045 x64 Horizon desktop (16GB RAM,110GB free,NVIDIA A16-1Q/VMware).
   Then run installation, editing, save/reopen and export-geometry tests.
   Native Windows11 x64 acceptance remains a separate pending gate.
   Check actual installer hash, graphics and all requested display scale factors.
   Build success or Windows ARM emulation cannot satisfy this gate.
2. Test Windows spaces, Unicode, supported path lengths and institutional install
   restrictions. No tested Windows path or graphics compatibility is asserted.
3. Reconcile the delivered real package against the adapter after preparation is
   complete. The expected final dataset folder was absent during implementation;
   no real-data import–edit–save–reopen–approve–export pass is claimed.
4. Supply the agreed released anatomical protocol and approved practice cases.
   Synthetic permitted correction, original-mask preservation and prediction-free
   loading passed in the actual application; permitted real practice integration remains pending.
5. Verify the real downstream loader and review the final installer licence
   inventory/signing/distribution requirements.

The application is **not ready for all250 cases** until those gates have been
closed and the end-to-end workflow repeated on the accepted Windows release.

Actual desktop coverage also includes completely blank segmentations saved/reopened
on the full source grid, ignored nearby phantom predictions with no hidden volume,
and explicitly permitted synthetic correction with verified source/version/checksum
and the original mask preserved separately.
