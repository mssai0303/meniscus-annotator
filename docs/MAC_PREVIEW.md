# Redesigned Mac preview — checked 6 November 2026

The preview launches the actual Meniscus Annotator module directly with the
existing pinned Slicer 5.12.4 Intel runtime under Rosetta on this Apple Silicon Mac.
It opens the oblique synthetic example with a visible acquired-slice slider and
counter. This is a development preview, not a Mac installer or Windows acceptance.

[Open the preview](/Users/saim/Downloads/Meniscus_Annotator_Preview_20261106/Open_Meniscus_Preview.command)

Full absolute Terminal command:

```sh
/bin/zsh /Users/saim/Downloads/Meniscus_Annotator_Preview_20261106/Open_Meniscus_Preview.command
```

The real window is titled **Meniscus Annotator — Synthetic practice**. The current
practice inputs have 17 and 23 acquired slices; the latter is oblique. These are
artificial shapes, not knee anatomy. Practice work remains in:

```text
/Users/saim/Downloads/Meniscus_Annotator_Preview_20261106/Practice_work/
```

The repaired launcher keeps the existing Synthetic_dataset and all Practice_work
checkpoints, uses Settings/Workspace.ini for separate preview preferences, checks
module registration and verifies the actual workspace before recording ready.
It resumes an existing practice case/slice. A fresh preview starts at slice 12 of 23
on the oblique example. Older failed-launch diagnostics are retained privately
in the preview folder, outside Git. The preview does not load or alter the real
250-scan Dropbox dataset. No further Windows acceptance is run during design review.

The launcher uses `/tmp/meniscus-runtime/Slicer.app`, the existing tested runtime.
If macOS removes that temporary runtime after restart/cleanup, restore that pinned
runtime before launching; the launcher reports a missing runtime rather than
performing downloads. Keep the launching Terminal open until the application is
closed normally. Clicking the launcher while the same preview is already running
reports that it is already open instead of opening the same case twice.

## Checks of this redesigned version

- Current module and interface hashes are recorded in
  [mac-preview-startup.json](evidence/mac-preview-startup.json).
- **182 actual native Slicer workflow assertions passed on the current code** with
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

Windows 10's baseline Slicer synthetic geometry/OpenGL probe passed and the user
confirmed image visibility. Scrolling/full redesigned-application acceptance is
not yet complete. Windows 11 remains untested, not declared incompatible.
