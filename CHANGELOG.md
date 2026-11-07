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
