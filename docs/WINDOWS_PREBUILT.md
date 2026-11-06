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

## Remaining acceptance

Read the generated receipt for the build's actual result. Neither a compiled
installer nor a successful hosted smoke test proves Windows11 mouse/keyboard,
resizing/high-DPI, offline annotation, crash recovery or the complete installed
import/edit/save/reopen/review/approve/export workflow. Complete
`packaging/WINDOWS_ACCEPTANCE.md` on an interactive Windows11 x64 machine before
claiming release support. Normal signing/security prompts and institutional
restrictions can apply.

## Proposed Horizon compatibility target — not verified

The proposed remote desktop is Windows 10 Enterprise build 19045 x64, 16 GB RAM,
about 110 GB free and NVIDIA A16-1Q/VMware graphics. Current official [Slicer
requirements](https://slicer.readthedocs.io/en/latest/user_guide/getting_started.html#system-requirements)
recommend Windows11; Windows10 is no longer tested upstream and may still work.
Graphics must expose OpenGL 3.2 or newer to the actual remote session. A GPU name
alone does not demonstrate that the Horizon display path exposes that capability.

First establish permission to install/run this research application and whether
the VDI profile/local Documents survives disconnect/logoff/recomposition. The
maintainer-only `packaging/windows-preflight.ps1` records OS, available memory,
GPU/driver names, disk space and resolved Documents/LOCALAPPDATA drive type, UNC/redirection clues and a
user-writable persistence probe without admin
requests, execution-policy changes or MRI access. Institutional script blocking
must be reported instead of bypassed. Reconnect to the same authorised session
and run `-VerifyProbe <probe-file> -Phase disconnect-reconnect`; repeat after
logoff/new session with `-Phase logoff-new-session` to check persistence; a successful immediate
write does not establish survival across profile reset or VDI recomposition.

Then install this fixed version in an ASCII path, open the committed synthetic
package and test native-plane rendering/editing. Only after rendering and
persistence succeed should the complete synthetic edit/save/reopen/approve/export
workflow be evaluated. Record actual Horizon client/session/display scaling and
the renderer's OpenGL details. No full-source superbuild or VM installation is
needed for this compatibility test. Windows11 interactive acceptance remains
pending separately.

A path reported on a local drive can still be an FSLogix/profile container or a
disposable VM disk. Path/drive checks cannot settle this. If installation or work
vanishes after logoff/recomposition, annotation must wait for IT-approved
persistent active-work storage and backup. A live Dropbox copy alone does not
solve the active-work requirement.
