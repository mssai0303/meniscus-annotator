# Meniscus annotation guide

This guide is for the doctor named in an assigned annotation package. The current
Windows build is a test candidate; complete Windows correction acceptance is
still pending. Use the supplied practice package while testing. A released drawing
protocol must be provided before research approval is enabled.

![Actual Slicer application with a synthetic oblique scan](images/annotation-workflow.png)

## Open and resume

After receiving the software and **complete assigned case folder**, extract any
ZIP files and keep a complete local copy. Install the supplied application, then choose **Open dataset** and select its top-level folder. The
coordinator supplies only assigned pilot cases, not the full selection containing
reserved test cases. Keep
`README.txt`, `case_index.csv` and all `Cases` subfolders together. The application
checks identities, hashes and geometry before offering editing.

A prepared correction package includes an explicit `correction_job.json`. Its
verified starting masks load as unreviewed predictions to correct, not completed
annotations. Missing or unresolved masks are blocked instead of replaced with
blank labels. MRI-only packages without a job require an explicit confirmation
before drawing from blank; the default is No. If you expected predictions,
cancel and obtain the correction package. Confirm the assigned reader identity
before opening ordinary work. Do not confirm another person's name for testing.

The header always identifies **Correction · Existing automated mask** or
**Blank annotation · No starting mask**. A slice outside the predicted meniscus
can have no coloured overlay even when the mask is loaded; inspect the acquired
stack rather than using a fixed slice number as a pass/fail rule.

For correction: inspect the MRI with the overlay both hidden and visible, check
the medial/lateral assignments, erase extra predicted tissue and add missing
tissue under the supplied drawing protocol. **Erase affects the active label
only**. Inspect every acquired slice, including slices outside the starting
prediction. The predictions are suggestions, not expert-approved anatomy.

Rows marked **Blocked** cannot be edited and Next case skips them. **Saved work
needs attention** means an existing checkpoint is incompatible or unavailable;
preserve the work folder and contact the coordinator instead of starting over.

The first connection proposes your operating system's Documents folder:
`Documents/Meniscus_annotation_work/<dataset_version>/`. You can choose another
**local** work folder then. It must be separate from the source dataset and
outside Dropbox/OneDrive. The remembered work location is shown by **Dataset → Show saved work**. Source images and metadata are never edited by this application.

Double-click a case or select it and choose **Open selected case**. Search by
OAI ID, visit or side; use the progress filter as needed. **Resume work** opens
the previous dataset/case. The last acquired slice is remembered. If you move
the downloaded dataset, choose **Open dataset** at its new location. The original
identity and hashes must match the existing work folder.

Keep the assigned job and protocol unchanged once work starts. They are bound
to saved checkpoints. Do not use **Help → Annotation setup** to substitute a
different job during a pilot; the coordinator must arrange a separate work
folder or a validated migration. A draft pilot produces practice results, not
approved training annotations.

## Draw and inspect

The header shows OAI ID, visit and knee side. The prominent bottom readout and slider count
**1 to N**, including every acquired slice. The primary view follows the acquired
planes even on a tilted scan. Letters at its edges describe actual physical
orientation; combinations such as `SLP` indicate an oblique direction. Secondary
reformats are for orientation and cannot be edited.

Choose the named label, then **Paint**, **Draw** or **Erase**. The active label,
tool, brush diameter and current-slice scope appear together. Medial is cyan
(label 1); lateral is orange (label 2). Painting one replaces overlapping voxels
of the other. **Uncertain area** is purple and may overlap either meniscus; it
is saved separately and never converted silently to background or a third
training class. Erase uncertainty using that label's Erase tool.

Paint and Erase use left-button dragging. **Draw** is a point-to-point contour:
left-click around the boundary, then right-click to close and apply a **filled
polygon on the current acquired slice**. It is not a freehand line tool. Use
Paint or Erase for edge touch-ups. Undo/Redo applies across labels during the
current editing session.
On reopening, recover work from saved checkpoints; the previous session's
in-memory undo history is not restored.

Use **Display and orientation** to show/hide labels, switch between outlines
and transparent fill, change fill opacity, reset the view or show reformats.
Use the slice slider, Previous/Next, mouse wheel or Go to for acquired-slice
navigation. Ctrl+wheel or right-button dragging zooms; middle-button dragging
pans. To adjust brightness and contrast, open **Display and orientation**,
choose **Window/level**, then **left-drag on the image**. Choose Paint, Draw or
Erase to return to annotation. Zoom and window/level remain in effect while
stepping through the case. **Cases** and **Tools** in the
header collapse the side panels. Panel widths and brush diameter are remembered.

## Review, save and approve

Scrolling does **not** mark a slice reviewed. After inspecting each slice,
including an empty one, use **Mark reviewed and next**. **Jump to → Next unreviewed slice** and
**Next flagged slice** help finish review. A flag records attention separately from
review. Any anatomical or uncertainty edit marks affected slices for rechecking.
Use notes for explanations; keyboard drawing shortcuts do not act while typing.

Use **Save draft** whenever needed. The application also saves every minute
when work changes, after explicit slice review, before switching cases and on
normal window close. The save indicator only reports success after saved files
have been reopened and checked. A failure keeps previous checkpoints intact;
check free space and permissions and retry before leaving the case. Do not run
two instances on the same case. If the application crashes, reopen the dataset
and case to restore the newest intact saved checkpoint. Unsaved changes since
the last checkpoint may be lost.

Before approval, review all slices, resolve all uncertainty/flags, and confirm
both compartment checkboxes. **Approve case** then requires your deliberate
confirmation. In the ordinary assigned-annotation workflow, the named reader is recorded as
both annotator and approver; this is not an independent second-reader review. Technical checks do not establish anatomical
correctness. Without a released protocol, approval is clearly marked **practice**.

The separate **SOFTWARE PRACTICE** workspace records explicit practice/test actors,
rather than a doctor. Its review and approval actions exercise software only. Every voxel in
its exported validity image remains zero, including after approval; neither
labels nor background are accepted research training annotations.

Editing an approved annotation creates a new draft. The previous approved
checkpoint remains unchanged. Re-review changed slices and approve a new version
when ready.

## Export and hand off

Choose **Export results**, then all approved cases or the selected case. Practice
exports require the explicit practice option and have `PRACTICE_ONLY` in the ZIP
name. Choose a destination; the application creates a versioned results ZIP in
a `Meniscus_annotation_results` subfolder. **Show exported file** opens the
containing folder. No MRI image is duplicated in the ZIP.

The export contains editable Slicer segmentations, full-grid medial/lateral
labels, separate uncertainty/validity images, slice-review tables, hashes and
annotation/approval metadata. It uses the latest preserved eligible approval,
even when a later unfinished draft exists. Never substitute a draft for an
approved export. Training code must respect validity and uncertainty records.
SOFTWARE PRACTICE exports use the `SOFTWARE_PRACTICE_ONLY-` prefix, remain separate, have all-zero validity images and
must not be used as accepted research annotations.

**Help → Annotation setup** is for a coordinator-supplied, dataset-bound JSON.
It records the protocol and explicitly permitted correction mask. An MRI-only
package without a job asks whether blank annotation is intentional. If you expect
automated masks to correct, choose No and ask for the assigned correction package. Do not edit job
configuration to promote a draft protocol yourself. Changing initialization or
protocol for existing work requires a separately coordinated work folder/batch.

## MRI view shortcuts

| Key | Action |
| --- | --- |
| Left / Right | Previous / next acquired slice |
| R | Reviewed → next slice |
| U / F | Next unreviewed / flagged slice |
| 1 / 2 / 3 | Medial / lateral / uncertain |
| P / D / E | Paint / Draw / Erase |
| Escape | Navigate without an active drawing tool |
| Ctrl+S | Save draft |
| Ctrl+Z / Ctrl+Y | Undo / Redo |

These shortcuts are scoped to the MRI view. **Help → Controls and shortcuts** also
provides local diagnostic details for an error. Keep diagnostics private; do
not send participant data or screenshots containing real identities to public
issue trackers.
