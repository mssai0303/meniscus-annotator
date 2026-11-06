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
