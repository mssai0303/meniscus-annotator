# Redesigned Mac development preview

The preview launches the actual Meniscus Annotator module directly with the
existing pinned Slicer 5.12.4 Intel runtime under Rosetta on this Apple Silicon Mac.
The single preview launcher now opens a real SOFTWARE PRACTICE case with a visible
acquired-slice slider and counter. This is a development preview, not a Mac
installer or Windows acceptance.

[Open the preview](/Users/saim/Downloads/Meniscus_Annotator_Preview_20261106/Open_Meniscus_Preview.command)

Full absolute Terminal command:

```sh
/bin/zsh /Users/saim/Downloads/Meniscus_Annotator_Preview_20261106/Open_Meniscus_Preview.command
```

The window is titled **Meniscus Annotator — SOFTWARE PRACTICE — not research annotations**.
It is restricted to two permitted cases copied without changing bytes from the
completed flat-folder package: one baseline scan with 37 acquired slices and one
month-72 oblique scan with 35. Your saved practice work remains in:

```text
/Users/saim/Downloads/Meniscus_Annotator_Real_Practice_20261106/Interactive_work/
```

Your exports go to the adjacent `Practice_exports/` folder. Automated QA work is
separate in `Automated_QA/` and is never loaded into your interactive practice.
The launcher resumes your saved case/slice; a fresh workspace opens the oblique
case. Original Dropbox inputs remain unchanged. All local real work, results,
exposure records and evidence stay outside the repository. The previous synthetic
dataset and practice checkpoints remain preserved in the original preview folder
for regression work. Windows acceptance is paused during Mac review.

The launcher uses `/tmp/meniscus-runtime/Slicer.app`, the existing tested runtime.
If macOS removes that temporary runtime after restart/cleanup, restore that pinned
runtime before launching; the launcher reports a missing runtime rather than
performing downloads. Keep the launching Terminal open until the application is
closed normally. Clicking the launcher while the same preview is already running
reports that it is already open instead of opening the same case twice.

## Checks of this redesigned version

- Historical synthetic-preview module and interface hashes are recorded in
  [mac-preview-startup.json](evidence/mac-preview-startup.json).
- **182 actual native Slicer workflow assertions passed** with
  the preview-specific settings constructor enabled: acquired-plane slider and
  numbering, first/last-slice edits, Paint/Draw/Erase, Undo/Redo, review invalidation,
  save/reopen, practice approval/export and unchanged source files.
- The redesigned legacy-folder regression also passed 182 assertions.
- **Seven fresh-process resume assertions passed**, including restored case,
  slice, notes and masks plus persistent tool/scope while panels are collapsed.
- **Five direct-startup assertions passed** through the real bootstrap without
  the test selecting a module. Welcome/module selector/Python/unrelated bars are
  absent from the focused workspace.
- Exact 1280×800 and 1440×900 logical captures were inspected. Preview.png is an
  actual Qt window capture, not a mock-up.

The new slider tests exposed and fixed an existing first-slice/reset mismatch:
view fitting had recentred the volume after the requested plane was set. The
requested acquired-plane translation is now restored after fitting and verified
on both axis-aligned and oblique fixtures.

Desktop computer-control access to Slicer was denied, so verification used the
application's native test harness, process checks, startup report and real window
captures. Launcher execution via Terminal was verified separately. The report's
window_visible flag and process identity are checked before claiming it is open.
An already-open window keeps its loaded code: save, close normally and relaunch
to pick up changes. A subsequent manual launch of the current code was confirmed
ready, its upright image was visually inspected, and saved practice state was
restored. This does not mean an older window updates itself automatically.

Windows 10's baseline Slicer synthetic geometry/OpenGL probe passed and the user
confirmed image visibility. Scrolling/full redesigned-application acceptance is
not yet complete. Windows 11 remains untested, not declared incompatible.


## Current controls and permitted software-practice checks

**Draw** closes a point-to-point contour into a filled polygon on the current
acquired slice: left-click points, then right-click to apply. Paint/Erase provide
left-drag touch-ups. For brightness/contrast choose **Display and orientation →
Window/level**, then left-drag. Right-drag zooms; middle-drag pans. Choosing a
drawing tool returns from window/level mode to annotation.

Two permitted complete MRI scans were exercised in the actual Mac application.
The initial practice workflow passed **318 checks**, followed by **36 restore
checks**. After the superior-up display correction, targeted verification passed
**203 checks**, followed by **36 restore checks**. A final status check passed
**27/27**, covering both permitted scans. These are distinct runs with overlapping
coverage, not counts to add into a single test total. The correction changes the
display orientation while preserving the acquired planes and stored source grid.

These runs use explicit non-Jeff software-practice actors. All validity voxels
remain zero, even after software review/approval. They are not accepted research
annotations or anatomical validation. Actual images, identities, private reports
and logs remain outside Git; committed screenshots use synthetic inputs only.

This runtime is **Intel Slicer 5.12.4 under Rosetta**, not a native ARM build.
