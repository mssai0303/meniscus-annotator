Additive correction permissions preserve the original job
=======================================================

An unresolved correction case may receive an explicit, case-scoped permission in
`correction_resolutions.json` beside `correction_job.json`. The original job file
and its canonical identity stay unchanged. Dataset identity, case metadata,
source MRI and the other cases' permissions stay unchanged too.

The registry uses `meniscus_correction_resolutions/1`. It binds the original job
identity and dataset identity. Each entry binds the exact case metadata identity,
source series key, series UID, MRI checksum, original unresolved rule identity,
prepared mask path/checksum/source/version and provenance path/checksum. Paths
must be the exact case's own `starting_mask.nii.gz` and `starting_mask.json`.
Only originally unresolved correction rules can be resolved. Existing ready rules
cannot be overridden. The application verifies the categorical native-grid image
using its existing checks; an updated hash cannot make wrong geometry valid.

`load_job_config` returns a `BoundCorrectionJob` when a registry applies. Its
mapping contains the effective permissions for the existing interface. Its
separate `source_job`, `base_job_identity` and `resolution_bindings` retain the
explicit source and amendment evidence. `canonical()` itself is unchanged.
`WorkStore.job_identity` is the original base identity, not the canonical hash of
the effective mapping. The original job must never be overwritten by serializing
the effective mapping.

Only the resolved case gets `initialization.case_resolution`. The checkpoint
manifest and export receipt preserve that binding. Opening, saving and exporting
recheck the registry, mask and provenance; missing or changed evidence fails
closed. Existing checkpoints for unaffected cases gain no fields and retain
their original job binding. No checkpoint migration or rewriting is performed.

Keep the registry with the package, and use an application containing this
backend contract. Older applications still see the original unresolved rule and
block the case. This extension makes no interface changes.

A case-specific compartment attribution is separate from the source pipeline's
accepted assignments. Its provenance must say which method was used and retain
the original pipeline failure. Technical verification does not establish tissue
identity, segmentation accuracy, expert review or accepted annotations. Original
binary predictions and detailed evidence remain in private analyst records.

The maintained preparation contract copy is deployed byte-for-byte from
`MeniscusAnnotatorLib/correction_resolutions.py`; it is not an independent rule
implementation. Full package receipts include the registry and prepared files.
Use those receipts for incremental transfer, rather than an MRI-only file list.
