# Windows installer from the official prebuilt runtime

The preferred packaging route wraps the pinned official Slicer Windows runtime
with this application module and offline dependencies in a real NSIS installer.
It avoids rebuilding Qt/VTK/ITK. This is a **wrapped Slicer distribution**, not the
custom-compiled application shell in the alternative full-source build. Upstream
Slicer branding/About information and runtime version 5.12.4 remain visible;
the focused workflow identifies itself as Meniscus Annotator 0.1.0.

The [official Slicer Slicelets documentation](https://www.slicer.org/w/index.php/Documentation/Nightly/Developers/Slicelets)
describes cloning the launcher, settings and App-real executable for a focused
workflow and separate settings. Complete compiled branding uses the separate
custom-application approach. This package follows the documented launcher route,
retains original executable bytes, adds its module and nibabel, and supplies an
installer, Start-menu shortcut and uninstaller. Jeff needs no terminal, Python,
Slicer installation, SCC account or runtime download.

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
settings defaults, licences and the practical guide with its synthetic screenshot.
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
It also checks duplicate-install rejection, safe refusal while a runtime file is
locked, and uninstall preservation using an unrelated synthetic text file. The
headless runtime import check has a bounded two-minute timeout.
`-RunIntegration` additionally attempts the existing native Slicer synthetic
rendering workflow; Windows11 interaction acceptance is still separate.

Outputs: `MeniscusAnnotator-0.1.0-Windows-x64.exe`, `installer-build.json` and
`installed-runtime-check.json` in the build folder. The receipt records the
installer SHA256, host and checks actually completed. Assembly checks on Mac
establish content/byte integrity only; they do not verify Windows execution.
This process is reproducible from pinned inputs and a recorded source commit;
installer timestamps may differ, so bit-identical output is not promised.

## Installed synthetic test kit

The payload whitelists `tests/slicer_workflow.py` and `tools/make_synthetic.py`
under `TestKit/`, with a small installed runner. It contains no second copy of
the application/core implementation: imports must resolve from the installed
`qt-scripted-modules` directory. Native test launchers use a separate
`MeniscusAnnotatorTest` Qt profile and fresh OS-resolved local test folders,
outside installation and ordinary annotation work. No MRI input picker or
source checkout is used. Generation explicitly uses the flat layout.

The versioned Start-menu Testing folder offers **Create synthetic examples**,
**Run synthetic workflow checks** and **Check synthetic resume**. The last item
requires a prior successful workflow run and reopens only that managed synthetic
run in a fresh process. The procedural geometric examples are not anatomical
teaching material. Reports state technical scope separately from anatomy and
independent-reader review.

A maintainer already using normal PowerShell can invoke the same native entries:

```powershell
# Set this to the actual installation folder if a custom location was chosen.
$install = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Meniscus Annotator\0.1.0'
& (Join-Path $install 'MeniscusAnnotatorExamples.exe')
& (Join-Path $install 'MeniscusAnnotatorChecks.exe')
& (Join-Path $install 'MeniscusAnnotatorResumeCheck.exe')
```

These commands use the bundled runtime, with no external Python or downloads.
`TestKit/RunSyntheticChecks.ps1` is an optional convenience, without administrator
requests or execution-policy bypasses. Routine annotation does not need it.

The test-kit whitelist/profile assembly has been checked on the development
host. Its new installed entrypoints have not yet been executed: Windows builds
and acceptance are on hold while the user reviews the redesigned Mac preview.
The earlier lifecycle receipt does not cover these added test-kit entrypoints.

## Hosted CI resources, limits and cost

The manual-only `Windows prebuilt installer` workflow uses `windows-latest`,
a 20-minute job timeout and one concurrent packaging job. It runs installation,
byte-integrity and runtime-import checks; synthetic rendering is optional. A
hosted Windows Server runner is not a Windows11 laptop and has no guaranteed
medical-viewer-capable GPU. No Windows VM is installed on the development Mac.
Private installer/evidence artifacts expire after one day; no public release is
created by this workflow.

Current [GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
list private standard Windows x64 runners with 2 CPUs, 8 GB RAM and 14 GB storage.
Budget about 5 GB free for this packaging route. Unlike the full-source
superbuild, it fits the standard runner's disk allowance. Runner images change;
the receipt records the actual image/OS. GitHub's [job limit](https://docs.github.com/en/actions/reference/limits)
is six hours, while this workflow deliberately stops after 20 minutes.

The current [Windows standard rate](https://docs.github.com/en/billing/reference/actions-runner-pricing)
is $0.010 per rounded-up minute: at most $0.20 compute for one 20-minute run,
before any included allowance. Actual account allowance, remaining credit and
budgets were not inspected. [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
currently gives Free accounts $12 and Pro accounts $18 monthly included compute;
artifact allowances are 500 MB and 1 GB respectively. These are shared resources,
not a promise of a free run. A roughly 300 MB installer retained for one day uses
artifact storage; repeated artifacts and other repositories also count. Keep
retention short and use account spending controls. No larger runner is needed.

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

Continue on the actual Horizon Windows10 configuration: install the final fixed
candidate, then exercise native-plane editing, review, save/reopen, fresh-process
resume, deliberate approval and export using synthetic data. Record resizing,
display scaling, input and offline behaviour. Complete the corresponding rows in
`packaging/WINDOWS_ACCEPTANCE.md`; Windows11 stays pending until it is actually
tested. Normal signing/security prompts and institutional restrictions can apply.
