# Changelog

## 0.1.0 — development

Initial focused Slicer annotation workflow, native acquired planes, explicit slice review,
immutable local checkpoints, technical validation, and approved export. Windows custom
application build is prepared; release gates are recorded in docs/WINDOWS.md.

### Workspace redesign (Mac preview)

- Prominent acquired-slice slider/counter, direct jump and persistent canvas context.
- Compact dataset/help menus, quieter case/annotation panels and consistent line icons.
- Direct workspace startup and isolated synthetic Mac preview preferences/work.
- Correct initial/reset acquired plane after view fitting; regression tests cover
  initial, first/last and oblique edits plus fresh-process restoration.
- Windows packaging progress retained; new acceptance testing paused for design review.

### Real-case software practice

- Isolated manual and automated practice actors, work and exports; no test approval
  is attributed to Jeff and every software-practice validity voxel remains zero.
- Superior-up acquired-plane display, explicit window/level interaction and
  immediate tool-overlay refresh without changing the stored image grid.
- Two permitted real scans exercised through editing, erase/undo, review,
  save/restart and geometry-checked export; private evidence remains outside Git.

### Explicit correction inputs

- Portable package-relative starting masks, explicit full correction jobs and
  blocked unresolved inputs; no missing-mask fallback to blank annotation.
- Actual-module tests erase existing medial/lateral prediction voxels, check
  exact undo/redo and preserve the original mask/provenance through export.
- A separate correction practice launcher/workspace preserves previous blank work.
