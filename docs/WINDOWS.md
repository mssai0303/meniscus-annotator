# Windows full-source custom application alternative

The preferred low-resource route is documented in [WINDOWS_PREBUILT.md](WINDOWS_PREBUILT.md).
It wraps official prebuilt Slicer in a real installer; this document retains the
alternative native custom-application superbuild for complete compiled branding.

The authorised private source repository contains a native Slicer custom application, adapted from the
[official template](https://github.com/KitwareMedical/SlicerCustomAppTemplate/tree/1863e64fe2c622a4de8021b145de180a91d8de52).
This is an implementation/build configuration. **No Windows installer has been
built or tested in this session.** The development host is macOS arm64; no local
Windows VM/compiler was discovered. A Mac launch never qualifies as Windows verification.

## Pinned baseline

The [official download page](https://download.slicer.org/) identified stable
Slicer 5.12.4 revision 34645 on 6 November 2026. The source tag resolves to
[`4e21c19d8360242d88d6ca2490bf52400441b8e1`](https://github.com/Slicer/Slicer/commit/4e21c19d8360242d88d6ca2490bf52400441b8e1).
The application branding is Meniscus Annotator 0.1.0; Slicer 5.12.4 is its runtime.
Stable release-type version formatting fixes the application version at 0.1.0
without a date suffix; this setting does not imply that application acceptance
has passed. The exact source revision pins Slicer's Python/VTK/ITK/CTK and other superbuild
dependencies. Additional application dependency: nibabel 5.3.2, SHA256-locked,
with typing_extensions 4.15.0. Python/NumPy/packaging/SimpleITK come from that
Slicer revision. `packaging/DEPENDENCIES.json` records the baseline.

Use Windows 11 x64, Visual Studio 2022 17.14 (Desktop development with C++),
v143 14.44.35207, Windows SDK 10.0.26100.0, CMake 3.31.6, Git for Windows
2.49.0.windows.1, Qt 5.15.2 **msvc2019_64** including WebEngine, and NSIS 3.11
including language packs. This toolchain is specified but **has not yet been
validated by a completed Windows build**. Reserve 80 GB and several hours.
Upstream [Windows build instructions](https://slicer.readthedocs.io/en/latest/developer_guide/build_instructions/windows.html)
explain the compiler and Qt prerequisites.

## Build

These are maintainer instructions; Jeff needs only the resulting installer.
Build source and output paths must be short and contain no spaces because of
Slicer/dependency build constraints. This restriction is distinct from dataset
and work paths, which must be tested with spaces/Unicode.

1. Clone the authorised private repository to `C:\D\M`. Check out
   the intended local commit, and ensure the tree is clean.
2. Install the exact prerequisites. Use a clean x64 developer PowerShell with no
   `PYTHONHOME`/`PYTHONPATH` and no unrelated Python installations on PATH.
3. Run:

   ```powershell
   & C:\D\M\packaging\build-windows.ps1 -BuildRoot C:\D\MA -QtRoot C:\Qt\5.15.2\msvc2019_64
   ```

Add `-RunIntegration` on an interactive desktop to execute the synthetic
application test and retain its report/screenshots in the build folder. This
checks the build-tree executable and does not replace clean-install testing.

The script configures the pinned Slicer superbuild, compiles the native custom
application and focused module, verifies bundled imports, then builds Slicer's
NSIS `PACKAGE` target. It writes a build receipt and SHA256 of installers under
`C:\D\MA`. `C:\D\MA\Slicer-build` contains the build outputs. Inspect exact
CPack output filenames; a script or portable launcher is not an installer.
Network access is required during the maintainer build to retrieve pinned
sources/wheels. All application dependencies are installed into the bundled
runtime **at build time**; routine installed use must require no downloads.
Automatic application updating and extension management are disabled to keep
an annotation batch on a fixed version.

## Licenses and release gates

Application/template adaptations use Apache-2.0 (`LICENSE` and
`packaging/TEMPLATE_NOTICE.txt`). The installer carries Slicer's license and
nibabel's COPYING file in `share/MeniscusAnnotator/licenses`. Slicer's bundled
runtime retains dependency distributions/notices, including Python packages'
`.dist-info` license files. Before distribution, verify that all upstream
notices, Qt LGPL material and applicable source/relinking information are
present; do not strip these from CPack output. A license inventory from the
actual artifact is a release requirement.

Run `packaging/WINDOWS_ACCEPTANCE.md` on a separate clean Windows account or VM,
recording actual installer hash, OS/build, display scaling and graphics. Test
offline launch and the entire import/edit/review/save/reopen/approve/export
sequence, then check exported outputs through the maintained checker and an
independent image reader. Build success alone is not acceptance. Sign only via
an authorised institutional signing process; unsigned installers can produce
normal Windows security prompts or face institutional restrictions.

No tested runtime path guarantee is asserted yet. Test Unicode/spaces and long
paths on Windows; until then use a short local work path and report any rejected
path clearly. Do not work directly in Dropbox. Release is blocked on a Windows
x64 build/test host with the pinned prerequisites and an interactive desktop.
No SCC login, MRI cohort access or protected test cases are needed to close
that platform gap.

## Optional private-repository CI

`.github/workflows/windows-build.yml` is manual-only and uses an owner-controlled
runner labelled `meniscus-build` (Windows x64). Provision the pinned tools first;
no runner has been provisioned or tested in this session. A GitHub-hosted Windows
runner does not include this exact Qt/toolchain baseline. Each run uses fresh,
short local paths and preserves outputs on the runner. It publishes neither an
installer nor a release. Enable the integration input only with an interactive
desktop. Record a separate clean-installed Windows acceptance after a successful
build; CI alone cannot establish mouse, scaling, offline or installer behaviour.
