# Mac review preview — 0.2.0 repaired review candidate

Windows x64 remains the release target. This Mac preview runs the actual
Meniscus Annotator module in pinned **Intel Slicer 5.12.4 through Rosetta on
Apple Silicon**; it is not a native ARM build or a browser mock-up.

[Open Meniscus Annotator](/Users/saim/Downloads/Meniscus_Annotator_Repair_Preview_20261108/Open_Meniscus_Annotator.command)

Full Terminal command:

```sh
/bin/zsh /Users/saim/Downloads/Meniscus_Annotator_Repair_Preview_20261108/Open_Meniscus_Annotator.command
```

The current frozen build is `60e5a33` / `v0.2.0-review-repair.3`. This revision has a separate preview profile and work folder. The earlier
November 8 preview, its launcher and all saved work remain intact. The new
preview uses read-only copies of the same two authorized development scans,
including the oblique acquisition, with their unchanged explicit starting-mask
permissions and practice protocol. It opens directly into the focused workspace.
The compact header contains case identity and save state; active compartment
and the Draw/Erase/Paint toolbar remain beside the MRI. Cases reopens the
remembered browser, and approval is in Case details and approval, with a visible Go to approval route after full-stack review.
The human practice actor is **Preview user (identity unverified)**. No automated
QA drawing, note, review or approval is loaded into this workspace.

Your work and exports are separate:

```text
/Users/saim/Downloads/Meniscus_Annotator_Repair_Preview_20261108/Practice_work_final/
/Users/saim/Downloads/Meniscus_Annotator_Repair_Preview_20261108/Practice_exports_final/
```

Earlier synthetic, real blank-practice and correction work folders are preserved.
Scripts, diagnostics, test evidence and real-image captures stay in the separate
private review area, outside this reader-facing folder and Git. The launcher
checks its own running PID and frozen application path; build receipts record the source hashes. It never force-closes another
window. Keep the launching Terminal open until closing normally. If macOS removes
`/tmp/meniscus-runtime/Slicer.app`, restore the pinned local runtime before launch;
there are no automatic runtime downloads.

## Try this revision

1. Confirm the case, knee side, active compartment and acquired-slice counter.
   Scroll through the full stack, including empty starting-mask slices.
2. Draw opens by default. Click around a boundary; right-click without dragging
   to close and fill. Use Erase and Undo/Redo. Paint remains for small additions.
3. Begin another contour and try Next slice or another label. The contour stays
   on its original target until Finish or an explicitly confirmed Discard.
4. Ctrl+wheel zooms; middle-drag pans. Show annotation is immediately available.
   Display and orientation adds transparent fill and window/level.
5. Switch **Task** to **Regions**. Choose a meniscus and Anterior horn, Body or
   Posterior horn. Region tools assign only inside the whole mask; return to
   Whole meniscus to add tissue. Show regions hides that overlay. Boundary
   uncertain and Regional assessment record unresolved boundaries or absence.
6. Save draft, close normally and relaunch to check restoration. Review and
   approval are separate actions; all preview outputs remain software practice.

Regional assignments start Not assigned. Their anatomical protocol remains
pending: no regional research approval is available and regional training
validity is zero everywhere. Whole-mask approval never approves the regions.
The preview loads no automated regional drawings or expert-boundary examples.

The header shows **Unsaved contour** while a contour is incomplete. Such points
are not saved checkpoints. Saving and autosave wait until the contour is finished
or discarded; prior verified checkpoints remain intact.

## Verification scope

See [VALIDATION.md](VALIDATION.md) for dated checks, exact source identity and
platform gaps. Synthetic fixtures cover left/right knees, both physical stack
directions and regular/oblique grids. Actual native controls, saved arrays and
physical coordinates are checked separately from visual inspection. Real-case
checks use isolated copies and retain private evidence. No technical check is an
anatomical assessment or a reader's research approval.

The revised Windows installer is built as a separate review candidate. It does
not replace the shared Dropbox installer. Hosted Windows checks and Mac Qt scale
simulations do not substitute for human review or new native Windows display
scaling acceptance. No further Horizon session is requested.

The launcher uses the existing pinned runtime at `/tmp/meniscus-runtime/Slicer.app` and checks that it exists. If that temporary runtime is removed, the maintainer must restore it. No runtime is downloaded or security setting changed by the launcher; a standalone Mac installer is not supplied. Earlier preview windows and their separate work folders are preserved.
