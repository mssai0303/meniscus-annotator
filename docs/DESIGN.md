# Interface system and verification

The module uses one neutral palette: surrounding panels #f3f5f7, text #25313c,
supporting text #52616e, accent #246a99 and borders #b8c2cc. The MRI canvas stays
black. Fixed segment colours are cyan medial, orange lateral and purple uncertainty;
all appear with names. Selection, tool and save/review status also use text.

Windows font choice is Segoe UI Variable → Segoe UI; development fallback Arial.
Controls use 11 pt, identity14 pt semibold and section headings12 pt semibold.
VTK orientation annotations use Arial. Spacing follows an8/12 px rhythm; buttons
have a28 px minimum content height plus padding and visible focus/hover/disabled
states. Qt logical dimensions respect OS scaling. No animation or gradients are
introduced. Label swatches are generated Qt primitives, not decorative icons.

Primary tools and notes remain visible at the tested1280×800 logical size.
Display/reformat controls collapse; a scroll fallback prevents inaccessible tools
on smaller heights. Header buttons collapse both panels; saved panel widths and
brush diameter are restored. Neutral panel backgrounds explicitly override
Slicer's theme for contrast. The main canvas uses native Slicer widgets.

Actual screenshots and development checks are in VALIDATION.md. Windows100%,
125%,150% and200% scaling, keyboard/mouse and clean installation are unverified.
The minimum window is1024×700 logical pixels; Windows usability at that size is
an acceptance task, not an established guarantee. Screens with200% scaling must
still provide enough logical workspace. No Windows ARM emulation is accepted as
Windows x64 verification.


## Redesigned workspace, November 2026

The actual module now uses a persistent application header, compact Dataset and
Help menus, an independent collapsible case dock and an organised annotation dock.
Native module navigation, Welcome, unrelated toolbars and the Python console are
hidden. A large 1…N acquired-slice slider, counter, Previous/Next and direct Go to
remain visible below the canvas. Native image overlays repeat the current slice,
label, tool and single-slice scope even when side panels are collapsed.

Icons are one restrained family drawn with Qt, with text on important controls.
Windows uses Segoe UI Variable/Segoe UI; macOS uses its Qt system font. Checkbox
selection includes an actual tick. Less frequent display, protocol and case-review
controls collapse. Orientation reformats use a narrow column while the acquired
plane keeps most of the viewport.

A first-slice error exposed by the new slider tests was corrected: FitSliceToAll
recentred the volume after the requested acquired plane had been set. The plane
translation is now restored after fitting; initial load and Reset view are checked
on axis-aligned and oblique examples, including first/last-slice paint and undo.

The current redesigned module passed 182 native workflow assertions with isolated
preview settings. Exact 1280×800 and 1440×900 logical captures were inspected on
the Apple Silicon Mac using the pinned Intel Slicer runtime under Rosetta.
Fresh-process restore passed seven assertions; direct startup passed five.
See MAC_PREVIEW.md. Windows acceptance is paused for the user's Mac design review.
