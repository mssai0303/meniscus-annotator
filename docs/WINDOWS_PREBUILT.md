# Windows installer from the official prebuilt runtime

The preferred packaging route wraps the pinned official Slicer Windows runtime
with this application module and offline dependencies in a real NSIS installer.
It avoids rebuilding Qt/VTK/ITK. This is a **wrapped Slicer distribution**, not the
custom-compiled application shell in the alternative full-source build. Upstream
Slicer branding/About information and runtime version 5.12.4 remain visible;
the focused workflow identifies itself as Meniscus Annotator 0.2.0.

The [official Slicer Slicelets documentation](https://www.slicer.org/w/index.php/Documentation/Nightly/Developers/Slicelets)
describes cloning the launcher, settings and App-real executable for a focused
workflow and separate settings. Complete compiled branding uses the separate
custom-application approach. This package follows the documented launcher route,
retains original executable bytes, adds its module and nibabel, and supplies an
installer, Start-menu application and Reader guide shortcuts, and uninstaller. Jeff needs no terminal, Python,
Slicer installation, SCC account or runtime download.

## Repaired review candidate — 0.2.0

The repaired review candidate is tag `v0.2.0-review-repair.3`, source
`60e5a33fb1b3a5cdd3076af78a86ab6ad71aafba`. Its identifiable review installer is
`MeniscusAnnotator-0.2.0-Windows-x64-60e5a33.exe`, 363,254,300 bytes, SHA-256
`e7f7f7e7a068ee7c0d213242e3767b58d500687d8994270067310daddf51549d`.
[CI 42559454615](https://github.com/mssai0303/meniscus-annotator/actions/runs/42559454615)
ran on Windows Server 2025 x64 build 26100, runner image 20261103.298.1. The
installer uses fast zlib compression; payload and acceptance checks are unchanged.

All **354 portable Windows tests** passed. Actual installation, all payload
hashes, runtime imports/source identity, synthetic generation, the simulated
legacy-registration guard, duplicate-install refusal, locked-runtime uninstall
protection, uninstall and fresh reinstall/work preservation passed. The installed
headless technical persistence route passed **55 checks**, including actual
Slicer editable segmentation storage, independent SimpleITK geometry, practice
markers/zero research eligibility and approved-version ZIP inspection. These
headless checks do not establish GUI drawing or visible Export-dialog acceptance.

The actual installer was independently extracted: all **9,603 payload hashes**,
all nine application source files against the tag, all three actual synthetic
guide PNGs, reader HTML, regional reader/TestKit and x64 native executables
matched. The final matching Word guide is 43,966 bytes, SHA-256
`cc5c80ae0d11026917bcb6f970a1da0e875d6ddab58377e8d6ce2e9f38615f2a`.
After CI, a review-candidate/remaining-Windows-checks note was added to this
separate guide. Its controls are unchanged, all six delivered pages were
re-rendered and inspected, and the installer bytes remain unchanged. The receipt
also retains the earlier source-tag guide hash.

The one fresh hosted system-renderer probe failed to create an ANGLE/EGL context
before rendering; no actual OpenGL version or MRI pixels were verified. Final
stderr contains no destroyed-widget callback trace. Native GUI Draw/review,
restart/export and scaling fields remain **BLOCKED**, not passed. Host policy
also prevented verified outbound isolation, so offline annotation/import
acceptance is not claimed. Current Windows 10 Enterprise 19045 interactive
acceptance and Windows 11 compatibility remain untested; earlier user testing is
evidence for its earlier revision. No further manual Horizon session is requested.

This is a repaired review candidate, not a fully verified production release or
acceptance of all 250 cases. See the committed
[exact CI summary](../packaging/evidence/windows-review-repair-ci.json). Earlier
0.1.0 and superseded 0.2.0 candidates are not substitutes for this installer.

The launcher sets `QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough` before Qt starts;
it does not force a reader scale factor. The installed runtime check records the
actual Qt version and policy. The interface supports smaller logical work areas
with scrolling and adaptive controls. Qt scale-factor simulation is separate
from native Windows display scaling at 125%, 150%, 175% and 200%.

New installation checks reject a registered 0.1.0 installation with instructions
to save, close and uninstall the old application first. Existing work and source
folders stay outside the application folder. Do not reopen migrated work in the
older application. The guard is tested using an isolated synthetic registration;
that does not establish a full historical-binary upgrade test. Reinstall and
uninstall checks verify preservation of external synthetic work.

A bounded installed headless check now exercises correction, native Slicer
segmentation storage, immutable checkpoints, review-journal restoration,
practice approval, exact-version export and an independent SimpleITK geometry
read. This technical persistence test can run without hosted graphics. It does
not establish GUI drawing, visible Export-dialog operation or anatomical review.
The ordinary reader GUI route has its own installed test aliases and receipts.

Only one fresh 45-second system-renderer probe runs by default on hosted CI.
Previously reproduced hosted OpenGL limitations are not retried for hours. A
failed graphics gate leaves GUI Draw/review/export/restart/scaling fields
**BLOCKED** while installation, headless persistence and uninstall checks still
run. It does not establish Windows desktop incompatibility.

## Previous visual and regional review candidate (preserved history)

Tag `v0.1.0-visual-regions-review.1`, source `b575000`, produces the separate
`MeniscusAnnotator-0.1.0-Windows-x64-b575000.exe` review candidate. SHA-256:
`daf4845a3ec51e9ea3d824bc8e71aed0abaa4aaadc45ee992d2808da7845e617`.
It was built and checked in [CI 42529049659](https://github.com/mssai0303/meniscus-annotator/actions/runs/42529049659)
on Windows Server 2025 x64 build 26100. All 315 portable tests, actual installation,
payload hashes, runtime imports, regional helper initialization, optional reader
import, synthetic generation and installation/uninstall safeguards passed. Three
synthetic guide figures, their references, regional documents and reader example
were independently extracted from the actual installer and hash checked.

Hosted rendering supplied actual OpenGL 3.0 and black image pixels, below the
required 3.2. Native drawing/regional/restart/export/scaling workflows remain
blocked; a green build is not their acceptance. Strict offline isolation could
not be verified under host policy. New-revision Windows 10 interactive testing
and Windows 11 testing remain pending. No further Horizon session is requested.
The shared installer and previous candidate remain unchanged. See the
[dated receipt](../packaging/evidence/windows-visual-regions-review-ci.json).

A maintainer can check out the immutable tag and run the command below. The
GitHub Actions job uses the same prebuilt route, a 20-minute bound and one-day
artifact retention. It needs network access for the locked build inputs and
space for extracted, assembled and installed copies of the roughly 1.1 GiB
runtime, plus the installer. It requires no full Slicer/Qt/VTK source build or
paid VM. Native workflow tests require a usable OpenGL context and actual MRI
pixels; missing hosted graphics are recorded as blocked, never passed.

## Locked inputs and contents

`packaging/prebuilt/dependencies.json` pins the official Slicer 5.12.4 revision
34645 Windows installer, its SHA512, 7-Zip 26.05, NSIS 3.13 and nibabel 5.3.2.
The official installer is 268,839,640 bytes (257 MiB); the assembled payload is
about 1.1 GiB. Its bundled NumPy 2.4.6, packaging 26.2, typing_extensions 4.15.0,
Python 3.12, Qt, SimpleITK and app-local VC runtime DLLs are retained. No MRI,
participant list, notes or saved annotations enter the installer.

`prepare.py` verifies the official installer/wheel hashes, preserves all 9,161
original runtime files byte-for-byte, and records every output file hash. It
adds the module, startup script, cloned launcher/native executable, isolated
settings defaults, licences and the practical guide with its three synthetic screenshots.
The startup file is selected through the documented `SLICERRC` environment
variable, avoiding unsafe command-line parsing of paths containing spaces.
Automatic application/extension update checks are disabled in this separate
settings profile to keep batches on one version. The installer only accepts an
empty destination and one registered copy of the fixed version per user. Uninstall
first locks the runtime files to reject running applications before any deletion,
then removes known files individually; unrelated files and
work outside the installation directory are preserved.

Original runtime dependency licence files are retained. The package also supplies
application, Slicer, nibabel, typing_extensions, NSIS, Qt LGPL/GPL/Chromium and
major native-library notices, with copied-notice hashes and exact source pointers
in its licences directory. This packaging evidence does not establish anatomical
acceptance.

## Reproduce on a Windows maintainer host

Use Windows x64, PowerShell 7 and Python 3.9+ for packaging only. Neither Visual
Studio nor Qt source/build tools are required. From a clean checkout:

```powershell
& .\packaging\prebuilt\build.ps1 -BuildRoot C:\D\MP -TestInstall
```

Use a fresh build folder without spaces; the installation check deliberately
uses spaces in its installation path. Upstream Slicer requires an ASCII-only
installation path; the installer rejects unsupported Unicode paths with a clear
message. Dataset/work Unicode handling remains a separate application test. The script downloads only
locked inputs using native curl, retries official mirror alternatives and rejects
any response that fails the same pinned hash (including download HTML pages).
`download-receipts.jsonl` records each result for diagnosing mirror failures. It extracts the runtime, assembles the payload, compiles the NSIS
installer, then optionally installs it, checks every installed hash and launches
its actual installed runtime without a main window to check imports/identity.
It also checks the legacy-registration guard, duplicate-install rejection, safe
refusal while a runtime file is locked, uninstall preservation, and a fresh
reinstall using external and unrelated synthetic work sentinels. The
headless runtime import check has a bounded two-minute timeout.
On hosted CI, the maintainer also attempts temporary outbound-deny firewall rules
for the normal/test native runtimes only. A successful import under those rules
has its own offline-import receipt. Rules are removed afterward; if host policy
prevents creating them, offline verification is explicitly not claimed. Reader
installation never requires firewall changes or administrator access for tests.
`-RunIntegration` additionally attempts the ordinary reader/draft-protocol GUI
route (including the visible Export selection/version dialog), its fresh-process
restoration, the installed correction route and its
fresh-process restoration, followed by the general native Slicer synthetic
workflow. Correction checks drive the actual Export/Cancel dialog buttons; the
native destination picker is redirected to the generated test folder. This is
injected-event automation, not human Windows interaction acceptance.

For development iterations, `-FastPackage` (workflow `fast_package=true`) selects
NSIS zlib compression. The default remains solid LZMA. This changes installer
compression/size, not the payload or acceptance checks; the build receipt records
`compression_mode`. The optional mode follows the
[NSIS SetCompressor syntax](https://nsis.sourceforge.io/Docs/Chapter4.html#varconstantsetcompressor).

Outputs: `MeniscusAnnotator-0.2.0-Windows-x64.exe`, `installer-build.json` and
`installed-runtime-check.json` in the build folder. The receipt records the
installer SHA256, source commit, application-source fingerprint, host and checks
actually completed. Dirty or unrecorded source checkouts are rejected before
building the installer. `BUILD-IDENTITY.json` in the installation records the
source commit and exact application file hashes without changing the checkpoint
format's application version. The filename/version 0.2.0 alone must never be
used to identify an accepted build. Assembly checks on Mac
establish content/byte integrity only; they do not verify Windows execution.
This process is reproducible from pinned inputs and a recorded source commit;
installer timestamps may differ, so bit-identical output is not promised.

## Installed synthetic test kit

The payload whitelists `tests/slicer_workflow.py`, `tests/slicer_export_dialog.py`,
`tests/slicer_draw_workflow.py`, `tests/slicer_regions_workflow.py`,
`tests/slicer_review_repair.py`, `tests/draw_fixture.py`, `tools/make_synthetic.py`, and the procedural correction fixture/workflow from
`packaging/prebuilt/` under `TestKit/`, with a small installed runner. It contains no second copy of
the application/core implementation: imports must resolve from the installed
`qt-scripted-modules` directory. Native test launchers use a separate
`MeniscusAnnotatorTest` Qt profile and fresh OS-resolved local test folders,
outside installation and ordinary annotation work. No MRI input picker or
source checkout is used. Generation explicitly uses the flat layout.

The Draw route runs eight known synthetic geometries (left/right × both physical
slice directions × regular/oblique), then a separate-process restore. Its layout
route can simulate Qt scale factors 1, 1.25, 1.5, 1.75 and 2 in separate processes and
records the actual available window/screen geometry. Simulated Qt scaling is not
human or physical Windows display-setting acceptance. These tools load the
installed application implementation; TestKit does not contain a second copy.

The reader's Start menu contains only **Meniscus Annotator**, **Reader guide**
and **Uninstall**. The synthetic generators and test executables remain internal
maintainer tools; they are not shortcuts in the doctor's workflow. Generated
examples contain explicit practice correction jobs and both labels. Each resume
tool requires a prior successful workflow run and reopens only that managed
synthetic run in a fresh process. The procedural geometric examples are not anatomical
teaching material. Reports state technical scope separately from anatomy and
independent-reader review.

A maintainer already using normal PowerShell can invoke the same native entries:

```powershell
# Set this to the actual installation folder if a custom location was chosen.
$install = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Meniscus Annotator\0.1.0'
& (Join-Path $install 'MeniscusAnnotatorExamples.exe')
& (Join-Path $install 'MeniscusAnnotatorChecks.exe')
& (Join-Path $install 'MeniscusAnnotatorResumeCheck.exe')
& (Join-Path $install 'MeniscusAnnotatorCorrectionChecks.exe')
& (Join-Path $install 'MeniscusAnnotatorCorrectionResumeCheck.exe')
& (Join-Path $install 'MeniscusAnnotatorDrawChecks.exe')
& (Join-Path $install 'MeniscusAnnotatorDrawResumeCheck.exe')
```

These commands use the bundled runtime, with no external Python or downloads.
`TestKit/RunSyntheticChecks.ps1` is an optional convenience, without administrator
requests or execution-policy bypasses. Routine annotation does not need it.

The newer correction entrypoints and refreshed installer require Windows
execution. Their presence in source is not a passing result. The older lifecycle
receipt at commit `6a562ef` predates the flat correction adapter and is not usable
evidence for the current dataset. Preserve that receipt as historical evidence.

## Installed diagnostic findings (7 November 2026)

The pinned candidate at commit `46ae45d` passed installed source/import checks.
Its old Testing shortcuts (now removed from the reader menu) were unusable: the canonical test launcher settings
were missing, and an empty test `HomeModule` aborted native startup before
Python. The assembler now supplies the canonical pair without overwriting each
alias's selected test action and uses `HomeModule=MeniscusAnnotator` in the
separate test profile.

[Bounded installed diagnostic 42394247782](https://github.com/mssai0303/meniscus-annotator/actions/runs/42394247782)
reused the exact original installer and recorded the ephemeral settings change.
The synthetic generator then passed on two flat correction cases, and all four
normal/test/native Python probes passed with unchanged application hashes.
The actual test settings path remained `MeniscusAnnotatorTest.ini`, separate
from the reader's `MeniscusAnnotator.ini`.

The correction and restart processes still failed before producing workflow
reports: the hosted Windows Server runner could not create a valid VTK OpenGL
pixel format and had no OSMesa fallback. This is **not a correction-workflow
pass**. Build a candidate with `run_integration=false` for Windows 10 Horizon
GPU testing; installation, byte checks, normal-runtime imports, synthetic
package generation and uninstall checks remain enabled. GUI test fields must
remain `NOT RUN` for that build. Windows 10 human interaction, correction,
restart and export acceptance remain pending; Windows 11 is untested.

The current maintainer build now probes actual synthetic rendering before
starting native workflow tests. It tries the system driver, Qt's software mode,
and a temporary alias of the **already bundled, hash-verified** `opengl32sw.dll`
beside the native executable. Qt documents both the
[software selection](https://wiki.qt.io/MesaLlvmpipe) and
[application-local Mesa route](https://wiki.qt.io/Cross-compiling-Mesa-for-Windows).
No driver is downloaded, no OpenGL capability/version is overridden, and the
alias never enters the installer. Each bounded attempt records actual reported
OpenGL, rendered synthetic pixels, stdout/stderr and any screenshot. Aliases are
removed and original installed payload hashes rechecked afterward.

An attempt must report actual OpenGL 3.2 or newer and render varied pixels in the
MRI canvas before it can enable native workflow checks. If every attempt fails,
the installer lifecycle checks continue, while native workflow fields explicitly
say **BLOCKED**, not passed. A successful installer job alone therefore remains
insufficient evidence of working editing or Windows desktop interaction. A
software-rendered hosted test, if successful, is also distinct from testing the
reader's physical GPU, Windows display settings or mouse interaction.
The generic VTK window's `SupportsOpenGL()` embedding callback is recorded only
as a diagnostic: its [default status is zero until the host supplies it](https://github.com/Kitware/VTK/blob/v9.6.0/Rendering/OpenGL2/vtkGenericOpenGLRenderWindow.cxx).
The probe gates on the actual context version and pixels, not that callback.

That candidate is now published as
[Windows test candidate 2](https://github.com/mssai0303/meniscus-annotator/releases/tag/v0.1.0-windows-correction-test.2)
from source `cb5919bea6a69e26d2396b509d9f2dad71f8cc68`. Its 362,213,587-byte
installer has SHA-256
`d09b4898dadbf328eac86c6857ad7f2072106a4b03de70bedfee1e18179bb5f6`.
Installation, payload/runtime checks, synthetic package generation and uninstall
checks passed; desktop GUI fields remain NOT RUN. This immutable candidate's
internal TestKit README still mentions removed Testing Start-menu shortcuts;
maintainers should run the named executables from the installation folder.
The reader application, reader guide and uninstall shortcuts are present.

## Hosted CI resources, limits and cost

### Final Zhang review candidate — 8 November 2026

[Run 42496348555](https://github.com/mssai0303/meniscus-annotator/actions/runs/42496348555)
built immutable tag `v0.1.0-zhang-review.4`, source
`ed3aa91fc75141b85ee6af3718c1fbc1a9f49e0c`. This resource revision preserves
the reviewed application/core bytes and explicitly bundles both approved
synthetic guide PNGs. All 268 portable Windows tests and fresh installation,
payload/runtime identity, synthetic generation and uninstall protections passed.
Independent NSIS extraction also verified every local guide-image reference and
both image hashes against the source and installed-payload manifest.

The final review copy is
`MeniscusAnnotator-0.1.0-Windows-x64-ed3aa91.exe`, 362,641,975 bytes, SHA-256
`5b6b917e4b1b80d443f1171bcd1ba1a8c76f60573059a28ce5f334907ed66bc2`.
The earlier review.3 binary is retained unchanged. Neither shared Dropbox
installer nor GitHub Release was replaced.

The fresh run reproduced the hosted graphics limit: Windows Server 2025 x64
build 26100; system rendering failed and both bundled software modes reported
OpenGL 3.0 with black pixels. All native Draw/correction/restart/export/scaling
workflow fields remain **BLOCKED**, not passed. Temporary aliases were removed
and installed bytes rechecked. Verified offline isolation was unavailable under
host policy. Windows 10/11 interactive and physical-DPI claims remain absent;
no new manual Horizon session is requested. See the current generic
[CI summary](../packaging/evidence/windows-zhang-review-ci.json).

### Earlier application candidate (review.3)

[Run 42494734647](https://github.com/mssai0303/meniscus-annotator/actions/runs/42494734647)
built immutable tag `v0.1.0-zhang-review.3`, source
`c6c6faa3024e2f1f9e29d8119adaeeb21c7dba51`, on Windows Server 2025 x64
build 26100 (runner image 20261103.298.1). All 268 portable checks passed.
Installation and complete payload hashes, duplicate-install protection,
installed runtime imports/source identity, synthetic correction-package generation,
locked-runtime uninstall protection and unrelated-file preservation passed.

The 362,144,201-byte installer has SHA-256
`feb24464706c3387247e26e923e4815cffcf956f6fa085f87091261ead2db726`.
Its application fingerprint matches the reviewed Mac Python source bytes.
The separate local review copy is named
`MeniscusAnnotator-0.1.0-Windows-x64-c6c6faa.exe`; no shared Dropbox installer or
GitHub Release was replaced or published.

Native workflow checks are **BLOCKED**. The system renderer failed; both trusted
bundled software modes reported actual OpenGL 3.0 and black canvas pixels, below
the required 3.2. No version override was used. Draw, correction, restart, export
and simulated scaling checks were therefore not marked passed. Test aliases were
removed and original installed hashes reverified. Host policy also prevented
verified outbound isolation, so offline imports/workflow are not claimed.

The user reports successful testing of an earlier Windows build; that history
does not verify this revision. Current Windows 10 interactive/DPI verification
and Windows 11 testing remain unclaimed. No additional manual Horizon session is
requested. The historical [CI summary](../packaging/evidence/windows-zhang-review.3-ci.json)
is committed; full synthetic receipts and logs remain in the separate maintainer
QA folder. Graphics failure on this hosted server does not establish Windows
incompatibility on a GPU-equipped desktop.

The first Zhang-review attempt,
[run 42494436850](https://github.com/mssai0303/meniscus-annotator/actions/runs/42494436850),
stopped before packaging: 259 portable checks passed and nine maintenance-layout
tests failed because native Windows path separators were compared with portable
`/` inventory names. The maintenance tools now serialize those comparisons with
`as_posix()`; no real migration or dataset operation was performed. The existing
268-test route passed locally after that narrow fix. That failed attempt produced
no installer or native-workflow evidence and is not an acceptance result.

The manual-only `Windows prebuilt installer` workflow uses `windows-latest`,
a 20-minute job timeout and one concurrent packaging job. It runs installation,
byte-integrity and runtime-import checks. The manual dispatch defaults to
`run_integration=true` for correction, Export-dialog and restart tests; it also
runs the correction contract tests before packaging. Synthetic rendering can be
disabled for diagnosis, but a build without it is not correction-accepted. A
hosted Windows Server runner is not a Windows11 laptop and has no guaranteed
medical-viewer-capable GPU. No Windows VM is installed on the development Mac.
Installer/evidence artifacts include the source commit in their artifact
name and expire after one day; no public release is
created by this workflow.

Current [GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
list public standard Windows x64 runners with 4 CPUs, 16 GB RAM and 14 GB storage;
private standard runners have 2 CPUs and 8 GB RAM. The repository is currently
public. Budget about 5 GB free for this packaging route. Unlike the full-source
superbuild, it fits the standard runner's disk allowance. Runner images change;
the receipt records the actual image/OS. GitHub's [job limit](https://docs.github.com/en/actions/reference/limits)
is six hours, while this workflow deliberately stops after 20 minutes.

[Standard hosted runner use in public repositories is free](https://docs.github.com/en/actions/concepts/billing-and-usage).
This route uses that standard runner, not a larger runner or a paid Mac VM.
Installer/evidence artifacts expire after one day rather than accumulating large
build binaries. A move to private hosting has separate plan/usage allowances.

## Declared platform requirements and actual verification

Windows11 is an upstream recommendation/test target, not an established launch
minimum for this pinned application. No Windows11-only guard is added.

| Component | Pinned declaration |
|---|---|
| Slicer 5.12.4 | Its [pinned requirements](https://github.com/Slicer/Slicer/blob/4e21c19d8360242d88d6ca2490bf52400441b8e1/Docs/user_guide/getting_started.md) recommend Windows11 and describe Windows10 as untested but potentially working. Its [platform check](https://github.com/Slicer/Slicer/blob/4e21c19d8360242d88d6ca2490bf52400441b8e1/CMake/SlicerBlockPlatformCheck.cmake) checks compiler versions; it does not enforce Windows11. |
| CPython 3.12.10 | [Exact source](https://github.com/python/cpython/blob/v3.12.10/PC/pyconfig.h) sets `Py_WINVER` to `0x0603` (Windows8.1); its [installer check](https://github.com/python/cpython/blob/v3.12.10/Tools/msi/bundle/bootstrap/PythonBootstrapperApplication.cpp) accepts Windows8.1+/Server2012+. This application bundles Python. |
| Qt 5.15.2 | Its [release support table](https://github.com/qt/qtdoc/blob/v5.15.2/doc/src/platforms/supported-platforms.qdocinc) lists Windows10/8.1/7 on x86/x64, with Windows10/MSVC2019 as a reference configuration. |
| nibabel 5.3.2 | Its [release metadata](https://github.com/nipy/nibabel/blob/5.3.2/pyproject.toml) requires Python>=3.9 and declares OS independence, without an additional Windows release minimum. |
| This installer/application | The installer checks Windows x64, an ASCII-only empty installation path and one registered copy of the fixed version per user. It does not check for Windows11. Normal annotation requires no system Python or PowerShell. |

These component declarations do not establish a minimum for every bundled native
library. Actual compatibility testing remains necessary. OpenGL 3.2 or newer and
persistent, user-writable work storage are required for the focused workflow.
Windows11 remains **untested by this project**, which does not mean incompatible.

## Current Horizon Windows10 test target

The user-provided target is Windows10 Enterprise build19045 x64, 16GB RAM,
107.9GB free and NVIDIA A16-1Q/VMware graphics. User-run checks reported successful
NIfTI voxel/full-grid verification and real OpenGL rendering with NVIDIA
A16-1Q/PCI/SSE2, OpenGL3.2.0, driver538.78. The user confirmed the synthetic
grayscale oval/ring is visible in the standard Slicer probe. This is baseline
Slicer compatibility evidence; it is not yet the focused application's complete
annotation workflow. Explicit scrolling and the installed application checks
remain separately recorded. No paid VM or full-source build is needed.

Documents and LOCALAPPDATA write probes survived disconnect/reconnect and a
sign-out/new session in the user's checks. Recomposition/profile-reset retention
still depends on the institution's configuration. A local drive can be a profile
container; do not infer permanent storage from a drive letter. Dropbox must not
be the only active working copy.

The maintainer-only `packaging/windows-preflight.ps1` records resolved locations,
UNC/redirection clues, drive type, GPU/driver and persistence probes without
admin requests or execution-policy changes. Institutional script restrictions
must be reported rather than bypassed.

## Remaining acceptance

The hosted Windows installer lifecycle/import tests passed, as recorded in
`packaging/evidence/windows-lifecycle-ci.json`. That receipt explicitly describes
its older source/layout scope. It does not prove desktop rendering, offline
annotation or human mouse/keyboard behaviour.

The current user constraint is to complete available automated work without
requesting another user-run Horizon session. This revision still lacks native
interactive Windows 10/11 verification of editing, review, save/reopen, approval,
export, physical display scaling and offline operation in a capable environment.
The earlier user-reported Windows success is historical evidence for that earlier
build. The new hosted graphics limitation and remaining rows in
`packaging/WINDOWS_ACCEPTANCE.md` stay explicit until a suitable environment is
available. Windows 11 is untested, not declared incompatible. No manual Horizon
request is part of this revision. The repaired review delivery records shared-folder
replacement separately from Windows GUI acceptance and recipient access.


The installed regional routes are `MeniscusAnnotatorRegionsChecks.exe`,
`MeniscusAnnotatorRegionsResumeCheck.exe` and
`MeniscusAnnotatorRegionsLegacyCheck.exe`. They use only procedural eight-grid
fixtures and the installed application. They test parent-masked regional drawing,
whole-mask edits, ten-segment Undo/Redo, separate reviews, native-grid files,
restart, export and unchanged legacy checkpoints. They are behind the same
actual-rendering gate in CI. The installed `Examples/read_regional_annotation.py`
is optional coordinator material; ordinary readers need no terminal or Python.
Regional protocol is pending and every regional training-validity voxel is zero.
