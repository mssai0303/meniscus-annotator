# Regional annotation extension

Schema: `meniscus_regions/1`. This extension retains the existing whole-meniscus
annotation/job identity and adds local, versioned regional work. It does not
modify source cases, correction jobs, original predictions or old checkpoints.
The anatomical regional protocol is **pending**. Software support is not a
validated anatomical division or an approved regional training reference.

## Labels and grid

Whole labels remain 0 background, 1 medial and 2 lateral. Their geometry, extent
and array convention remain unchanged. The separate `regions.nii.gz` uses:

| Value | Meaning | Parent whole label |
| --- | --- | --- |
| 0 | Outside both whole menisci; not accepted background | 0 |
| 1 | Medial anterior horn | 1 |
| 2 | Medial body | 1 |
| 3 | Medial posterior horn | 1 |
| 4 | Lateral anterior horn | 2 |
| 5 | Lateral body | 2 |
| 6 | Lateral posterior horn | 2 |
| 7 | Medial unassigned | 1 |
| 8 | Lateral unassigned | 2 |

Every file spans the full original acquired grid. Values 7 and 8 explicitly
record **unassigned meniscal tissue**, never accepted background. Zero is permitted
only outside both parents; regional validity remains zero there. Every parent
voxel belongs to one of its three named regions or its explicit unassigned value.
`regional_uncertainty.nii.gz` is a separate binary map restricted to meniscal
tissue and may overlap an assigned region. Whole-mask uncertainty also excludes
regional validity. Neither uncertainty layer becomes a training class.

A region is confined to its fixed parent label. Region assignment replaces a
previous region at the same voxel without modifying the parent. Removing a
region returns its tissue to unassigned. Whole-mask changes remove assignments
and regional uncertainty outside their permitted parents; newly added tissue
starts unassigned. All affected acquired slices require regional re-review.
Previous immutable versions remain intact. No image-space split, slice direction,
filename, side of screen or equal subdivision defines an anatomical region.

## Review and protocol

Regional metadata records its own schema, fixed label dictionary, annotator,
source identity/hash, application/runtime identity, protocol provenance, review
records and completion state separately from whole-meniscus review/approval.
The initial regional protocol is `meniscus-regions-pending-1`, status `pending_expert_protocol`,
with expert boundaries and handling of roots, tears, maceration, surgery and
uncertain tissue explicitly unresolved. This local extension does not amend the
existing job identity or whole-meniscus protocol.

Each acquired slice records medial/lateral regional review separately. Each
region can be recorded as not assessed, present, absent or uncertain, with a
note. An absent region is permitted to contain no voxels; no minimum volume or
artificial tissue is required. An absent declaration cannot coexist with assigned
voxels for that region. Uncertain boundaries and flags remain unresolved work.
Technical regional completion requires all parent voxels assigned, explicit
review of both compartments on all acquired slices, each region considered and
no unresolved uncertainty/flags. Completion is distinct from saving and research
approval. The pending protocol prevents regional research approval and produces
all-zero regional training validity, including software-practice output.

Experts must supply versioned, documented anatomical definitions before regional
research approval can be enabled. This revision does not invent those definitions
or claim that existing post-processing supplies validated horn separation.

## Checkpoints and export

New regional checkpoints retain the existing base payload and add
`regions.nii.gz`, `regional_uncertainty.nii.gz`, `regional_validity.nii.gz`,
`regions.json` and `regional_review.csv`. An optional versioned manifest extension
binds all five payload hashes to the same source identity. Atomic commit,
recovery, duplicate-session locks and independent file reopening cover them.
Older whole-only checkpoints reopen with regions Not assigned in memory. Merely
opening them does not rewrite their metadata, attribution, job or checkpoint.
A later explicit save creates a new extended checkpoint.

Exports include both representations and their review, dictionary, protocol,
validity and source provenance. Whole-meniscus approval does not approve regions.
Training consumers must require explicit regional validity and exclude unassigned,
uncertain, unreviewed, protocol-pending and software-practice voxels. The example
reader is a validation/loading example, not integration with a training pipeline.
