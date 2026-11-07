# Changelog

## 0.1.0 — development

### Correction pilot repairs — 7 November 2026

- Repair the actual Export dialog; verify visible Export/Cancel, Return/Escape,
  selected-only archives and cancellation with native Qt interactions.
- Confirm intentional blank initialization and assigned reader identity before
  creating ordinary work; keep the initialization method visible while editing.
- Support explicitly named readers without relabelling historical checkpoints.
- Show blocked cases and unavailable saved work accurately; skip blocked cases
  with Next and preserve the current case when an unavailable case is selected.
- Record source hashes and build identity in new checkpoints and the About view.
- Add installed synthetic correction/restart fixtures to Windows packaging and
  CI. Windows desktop acceptance remains a separate gate.

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
