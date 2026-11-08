# Changelog

## Draw workflow review — 8 November 2026

- Draw is the case-opening default; Draw/Erase lead the compact tools, and brush
  size appears only for Paint/Erase. One contextual instruction replaces canvas
  text, while knee side, active label, slice review and save state remain visible.
- Native unfinished contours have visible points and explicit Finish/Discard;
  changing targets, saving, review and normal close are blocked until resolved.
  Right-drag no longer accidentally fills a contour.
- Removed redundant same-plane reprojection that made native Draw reject later
  points on a real oblique scan. No image, contour RAS point or label geometry is
  moved or resampled by this fix.
- Thin outline display, accessible visibility control and collapsible notes and
  details; existing masks, protocols, saved-file schema and attribution retained.
- Eight-way synthetic geometry/UI tests, isolated two-scan checks and preserved
  checkpoint compatibility are distinguished from Windows automation/human review.
- Windows review packaging adds bounded, recorded test-only rendering attempts;
  the shared installer remains unchanged pending review.

## 0.1.0 — development

### Correction pilot repairs — 7 November 2026

- Provide a bundled offline reader guide and a simple Start menu with the app,
  guide and uninstaller; maintainer testing shortcuts are not shown to readers.
- Separate named-reader default work folders and saved-location preferences by
  immutable assignment; preserve legacy and software-practice work locations.
- Keep the assigned reader visible and confirm identity before choosing a work
  location. Actual Mac dialog checks cover two readers on the same dataset.
- Correct Windows test launcher action dispatch and home-module defaults; hosted
  OpenGL rendering remains insufficient for interactive workflow acceptance.

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
