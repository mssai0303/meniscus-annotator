# Mac review preview — Draw workflow

Windows x64 remains the release target. This Mac preview runs the actual
Meniscus Annotator module in pinned **Intel Slicer 5.12.4 through Rosetta on
Apple Silicon**; it is not a native ARM build or a browser mock-up.

[Open Meniscus Annotator](/Users/saim/Downloads/Meniscus_Annotator_Mac_Preview_20261108/Open_Meniscus_Annotator.command)

Full Terminal command:

```sh
/bin/zsh /Users/saim/Downloads/Meniscus_Annotator_Mac_Preview_20261108/Open_Meniscus_Annotator.command
```

The preview uses read-only copies of the same two authorized development scans,
including the oblique acquisition, with their unchanged explicit starting-mask
permissions and practice protocol. It opens directly into the focused workspace.
The human practice actor is **Preview user (identity unverified)**. No automated
QA drawing, note, review or approval is loaded into this workspace.

Your work and exports are separate:

```text
/Users/saim/Downloads/Meniscus_Annotator_Mac_Preview_20261108/Practice_work/
/Users/saim/Downloads/Meniscus_Annotator_Mac_Preview_20261108/Practice_exports/
```

Earlier synthetic, real blank-practice and correction work folders are preserved.
Scripts, diagnostics, test evidence and real-image captures stay in the separate
private review area, outside this reader-facing folder and Git. The launcher
checks its own running PID and loaded source hash; it never force-closes another
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
5. Save draft, close normally and relaunch to check restoration. Review and
   approval are separate actions; all preview outputs remain software practice.

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
