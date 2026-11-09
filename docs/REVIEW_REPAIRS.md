# Independent review repairs for version 0.2.0

The repaired review candidate is `v0.2.0-review-repair.3`, application source
`60e5a33fb1b3a5cdd3076af78a86ab6ad71aafba`. It is suitable for reviewer evaluation,
not routine research annotation. Native Windows GUI/DPI/offline acceptance and
expert regional definitions remain pending. Technical acceptance is not anatomical
validation or independent second-reader approval.

The original review was checked against the current checkout before changes.
Reproduced defects, conditional risks and visual suggestions were treated
separately. The source dataset, original predictions, correction job, protocol,
existing reader attribution and immutable checkpoints were preserved.

| Finding | Disposition | Repair and evidence |
|---|---|---|
| B1 | Fixed | Ordinary draft-protocol Export defaults to clearly identified practice results. Visible default/selected/Cancel/successful ZIP and unapproved/empty-selection dialogs were exercised. |
| P1 | Fixed | Effective authorized reader binding is established before regional validation. Whole-only and regional legacy GUI fixtures pass; the one existing saved human-practice checkpoint also validates read-only with unchanged bytes (the other case has no saved checkpoint). |
| P2 | Still open in part | Verified Qt policy before applying PassThrough; smaller logical layouts, readable case identity and full tool names repaired. Mac 100–175% simulations pass. This Mac cannot verify a complete 200% desktop below the 800×480 minimum; native Windows DPI remains pending. |
| I1 | Fixed | Named task/region/assessment button selectors replace target dropdowns. Remaining filter has a visible chevron, light popup, focus/disabled states and wheel guard. |
| I2 | Fixed | Assessment-only changes preserve slice review. Conflicting absence/content and uncertainty remain attention conditions; actual mask changes invalidate affected review. |
| I3 | Fixed | Repeated unchanged review preserves approval. Export lists included/excluded checkpoint versions and requires explicit earlier-approval selection when newer drafts/journals exist; ZIP values were compared with the selected checkpoint. |
| I4 | Fixed | Window shortcuts work after panel interaction and remain inactive in text fields. Focus does not require a click that adds a Draw point. |
| I5 | Fixed | Anterior-left acquired-plane presentation is a right-handed view transform only. Physical slice cues use source geometry and explicit knee side; eight orientations and full-grid save/reopen/export pass. |
| I6 | Fixed | Relative physical-position advisory uses tolerance and minimum size. Missing/tiny/close masks are inconclusive; no automatic relabeling or anatomical certification. |
| I7 | Fixed | Pending target/point count and Finish/Discard are conspicuous. Normal close offers Finish, Discard or safe Keep drawing; navigation cannot silently misapply a contour. |
| I8 | Fixed | Completed whole-stack review shows a visible Go to approval route and its remaining requirements. Saving remains separate. |
| I9 | Fixed | New cases open on a useful masked slice; resumed positions, including empty slices, are restored. Blocking range-change signals fixes longer-to-shorter case switching. |
| I10 | Fixed with stated limits | New work uses per-user local application data, write checks and known cloud/network-location checks. Existing locations are preserved; detection cannot establish every institutional sync policy. |
| I11 | Fixed | Atomic checkpoint-bound review journals replace full-volume saves for unchanged masks. Abrupt restart recovery passes; final real-practice review clicks measured approximately 0.13–0.23 s including driver waits. Old checkpoints/journals are retained. |
| I12 | Fixed | Shared status vocabulary distinguishes practice/research approval and readiness. Saving, Saved, Unsaved changes and Save failed are distinct; failure state survives until successful persistence. |
| I13 | Fixed | Ordinary protocol practice and software practice have explicit separate purposes. Generated practice images carry header markers. Reviewed-voxel validity is separate from zero practice research eligibility; pending regional targets remain excluded by the example reader. |
| O1 | Intentionally handled differently | Use native opaque outlines, default 2 px with 1–4 px control and adjustable fill. No custom halo renderer, resampling or boundary changes. |
| O2 | Fixed | Pending points/lines follow the active target color, while explicit target text and Finish/Discard distinguish them from saved masks. |
| O3 | Fixed | The next-step area presents one primary action for review, contour completion or approval; ordinary actions stay quiet. |
| O4 | Fixed | Neutral light panels, menus, popup text, scrollbars and dialogs have explicit contrast and selection states, including under the Mac's dark OS chrome. |
| O5 | Fixed | Reader and dataset appear with case identity and remain available through Reader and dataset with full paths. Long context text has a full tooltip/accessibility name. |
| O6 | Fixed | Remembered or assigned reader identity requires deliberate confirmation on ordinary restart/setup; historical attribution is never overwritten. |
| O7 | Fixed | Draw opens by default and leads the compact toolbar. Equal readable tool widths retain Erase/Paint; brush size appears only when applicable. |
| O8 | Fixed | Assessment headings and choices name the selected compartment/region. Body is explicitly inside the complete meniscus. |
| O9 | Fixed | Compartment transfers show a concise notification with Undo. View orientation and the advisory never transfer or relabel tissue. |
| O10 | Fixed | Six-page Word guide and bundled help explain research use, unsigned installation, correction/review/export, practice limits and work-preserving updates. Every rendered Word page was inspected. |

## Verification scope

- **354 portable tests** pass on Mac and the final Windows CI checkout.
- Latest actual Mac UI: **224 ordinary workflow / 21 restart checks**. Modal
  controls use visible Qt button activation; panel focus and native effects use
  injected Qt/VTK events. These are not OS-pointer or human-reader acceptance.
- Native geometry: **130 orientation**, **1,019 Draw workflow / 172 restart**
  checks across left/right × both stack directions × regular/oblique fixtures.
  The final small-layout/teardown edits do not change editing/render geometry.
- Save/journal failure feedback: **66 injected-backend-fault GUI checks**. Failed
  operations retain work and immutable hashes, show Save failed and recover on
  explicit retry; no real disk was filled.
- Legacy UI fixtures: **38 whole-only / 39 regional**; review crash recovery:
  **44 write / 26 recovery**; unapproved/empty-selection Export: **36**.
- Final layout: **297 checks per 100/125/150/175% Mac Qt simulation**. At short
  heights regional Undo is reached through ordinary vertical scrolling; Save,
  review and slice navigation stay fixed. Mac 200% and native Windows DPI are
  explicitly not passed.
- The two already authorized real practice copies completed correction, exact
  Undo/Redo, complete-stack review, save, practice approval, visible selected-case
  export and independent native-grid ZIP inspection (**367 / 28 restart checks**).
  No expert anatomical reference or doctor approval was created. Private case
  evidence and images remain outside Git and the clean reader delivery.
- Final Windows Server 2025 x64 build 26100: actual installer, payload integrity,
  installed runtime imports, **55 headless technical persistence/export checks**,
  installation guards, uninstall and reinstall/work preservation pass. The fresh
  hosted ANGLE render-context creation fails before image rendering. GUI and
  strict offline acceptance were not passed; Windows 10/11 interactive checks
  remain pending for this revision.

The [Windows build receipt](../packaging/evidence/windows-review-repair-ci.json)
records exact artifact hashes and platform limits. Runtime remains pinned to
Slicer 5.12.4; Mac uses Intel Slicer through Rosetta, not native Apple Silicon.
The [contract](CONTRACT.md) defines journal recovery, version export and eligibility.
