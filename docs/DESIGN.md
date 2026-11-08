# Visual specification — clinical workstation revision

Revision: visual review 1, November 8, 2026. Windows x64 is the release target;
macOS uses the same Qt workspace with its native system font. This revision retains the existing Slicer drawing engine and whole-meniscus
schema. A separately versioned regional extension was added at the user’s request.

## Composition

The MRI is the dominant region. A single-line header contains the application
name, Cases, case ID/visit/knee side, a stable save-state field and compact menus.
Practice appears once in the header state; detailed provenance and reader identity
remain accessible in Case details. The native Slicer Welcome, module selector and
unrelated toolbars remain hidden.

The case browser is about 220–230 logical pixels wide and can be collapsed with
Cases. The annotation panel is about 240–250 logical pixels wide. User-selected
panel visibility and width persist, while case selection can deliberately reopen
the browser. A focused workspace keeps annotation tools beside the image with
Cases closed. Dock transitions must not lose work or change the image view.

The footer has two compact rows: acquired-slice counter, previous/slider/next,
direct slice entry, Mark reviewed and next, and Save draft; then review progress
and one contextual instruction. Finish contour and Discard occupy that instruction
row only while a contour is unfinished. Approval moves to Case details and review,
next to its required compartment confirmations. Jump actions remain available in
a compact menu. At small logical sizes secondary status text may wrap or move,
but navigation, Save and contour completion must remain accessible.

## Typography and controls

Ordinary controls use 11 pt regular text. Windows selects Segoe UI Variable when
available, otherwise Segoe UI; Mac selects the Qt system UI font. Explicit normal
weight is the base. Only application/case identity and small section headings use
semibold. Runtime checks record resolved QFontInfo family, point size and weight;
stylesheet declarations are not considered verification.

Use a neutral gray panel surface (#e9edf0 range), near-white input fields and dark
slate text. One blue accent identifies selection, focus and the relevant primary
action. Ordinary actions are quiet flat desktop controls, with subtle hover states;
selected tools have a blue-tinted surface and border. Use consistent 30–32 logical
pixel control heights, 6/8/12 logical pixel spacing and modest 3-pixel corners.
Visible keyboard focus and readable disabled controls are required.

Draw / Erase / Paint form a compact text-beside-icon toolbar using the existing
line-icon family. Draw stays the default. Undo/Redo are supporting actions. Brush
size appears only for Paint and Erase. Medial, Lateral and Uncertain area retain
explicit names and fixed cyan/orange/purple meanings. Secondary display settings,
notes, flags and case details collapse; their contents must fit the panel without
horizontal scrolling. Repeated banners and large white action boxes are removed.

## Image and information integrity

The canvas remains dark with unobstructed physical orientation letters. Existing
mask boundaries remain thin; outline-only and adjustable fill are retained. Pending
contour points remain visibly different from committed labels. No display change
may alter source geometry, mask voxels, label identities, zoom or window/level.

Save status occupies one stable header location. Saving, slice review and case
approval remain different actions. Practice restrictions, source attribution,
reader identity and complete initialization provenance remain truthful and
accessible. Empty starting-mask slices are described neutrally.

The instruction line changes with the current task. Draw says “Click around the
boundary. Right-click to close and fill.” Pending contours keep Finish/Discard and
the existing navigation/save safeguards; typography or layout must not weaken them.

## Verification and scope

Inspect the actual Slicer application at 1280×800, 1440×900 where the desktop
permits, and a smaller work area. Record actual logical sizes and device-pixel
ratios. Check resolved fonts, clipping, selected/focus states, both collapsed docks,
notes/details expansion and pending contours. Exercise native Draw, Finish,
Discard, Erase, Undo/Redo, navigation, Save, restart and Export using synthetic
fixtures and the same two authorized real practice copies. Keep real pixels and
identifiers private. Retain the geometry and failure-condition regression route.

Mac Qt scaling simulations are not Windows DPI acceptance. A fresh Windows x64
installer must receive available automated integrity/install/runtime checks; hosted
OpenGL limitations and any unexecuted interactive workflows must be reported.
Previous Windows tests do not verify this revision. The shared installer is not
replaced during review.

## Regional task extension

The compact annotation panel uses Meniscus Medial/Lateral, Task Whole meniscus/
Regions, and a single Region selector for Anterior horn, Body or Posterior horn.
There are no six-region tiles. Boundary uncertain is explicitly separate from
whole-mask Uncertain area. Show regions is an immediate overlay control. Regional
assessment/note controls collapse and identify the selected region.

The task and full target remain visible beside the image; when Tools is closed,
the one contextual instruction includes them. Review progress follows the active
task and parent compartment. Case details keeps whole approval separate; regional
research approval is unavailable while the anatomical protocol is pending.

All six regional segments share the existing native Slicer editor and undo
snapshots with their whole parents. Parent masking limits edits; native-grid
validation and regional reconciliation remain data checks, not display styling.
See REGIONAL_CONTRACT.md for unassigned values, uncertainty and pending validity.
