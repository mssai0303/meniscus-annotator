# Meniscus Annotator 0.1.0

A focused research annotation module and Windows custom-application build for
3D Slicer **5.12.4, revision 34645**. The MRI remains on its complete acquired
grid, including tilted sagittal planes. No model is trained or downloaded.

**Development preview; Windows correction acceptance is in progress.** The actual Slicer desktop
workflow has been exercised on synthetic scans and two explicitly permitted
software-practice MRI scans using Intel Slicer 5.12.4 under Rosetta on macOS.
This is not a native ARM runtime; practice outputs are not accepted research
annotations and their validity images are entirely zero. A wrapped Windows installer passed hosted installation/import/lifecycle checks;
the redesigned interface has not yet completed Windows acceptance. The flat-folder
input package has passed two-case Mac software-practice checks; the complete
250-case production batch has not been accepted. A released anatomical protocol has not been supplied. Do not
use this version as an accepted production release for 250 cases.

The current review tag is **v0.1.0-visual-regions-review.1** (`b575000`). Its
compact clinical workspace preserves native Draw/Erase/Paint and adds a separate
regional task for anterior horn, body and posterior horn within each whole
meniscus. The complete medial/lateral masks remain primary. Regional work starts
Not assigned and has separate review, uncertainty and full-grid files. Expert
regional definitions are pending, so regional research approval is unavailable
and regional validity is zero everywhere.

The prepared dataset, predictions, existing job/protocol and old checkpoints are
preserved. New regional saves add a versioned optional extension without rewriting
historical files or attribution. Actual Mac and Windows automation scopes are
recorded separately in [VALIDATION.md](docs/VALIDATION.md).

- [Open the checked Mac preview](docs/MAC_PREVIEW.md)
- [Reader quick start](docs/QUICK_START.html) and [detailed annotation guide](docs/USER_GUIDE.md)
- [Input/output and job contract](docs/CONTRACT.md)
- [Regional schema](docs/REGIONAL_CONTRACT.md) and [technical reader example](docs/REGIONAL_READER.md)
- [Windows reproducible build](docs/WINDOWS.md)
- [Test results and release gaps](docs/VALIDATION.md)
- [Test responsibilities](docs/TEST_PLAN.md)
- [Changelog](CHANGELOG.md)

## Reader delivery

The primary acceptance target is Windows 10 Enterprise x64 build 19045 on the
available Horizon desktop. Windows 11 remains untested. The standalone installer
bundles Slicer and the application dependencies; the assigned MRI package is
provided separately. Each ordinary assignment names its reader before work
starts. MRI inputs remain unchanged, and readers return one verified results ZIP.
The quick-start guide is local HTML with no online fonts, scripts or resources.

## Development setup

Use the exact pinned Slicer release from [the official download page](https://download.slicer.org/).
A module is the development route; the reader's Windows product will include
its runtime in the custom application's installer. Do not install the PyPI
package named `slicer`; it is unrelated.

For local module development only, use Slicer's Python console once to install
`nibabel==5.3.2` (or install the verified wheel offline using PythonSlicer).
These dependencies are bundled at **build time** in the Windows application;
Readers will not need Python, pip, a console, a GitHub account or runtime downloads.

In Slicer: Edit → Application Settings → Modules → Additional module paths →
add this repository folder. Launch with the development entry point below to open **Meniscus Annotator**
directly. The module opens the focused MRI layout. Use **Open dataset** to select a package.
For a development launch:

```text
Slicer --no-splash --ignore-slicerrc --additional-module-paths <repository> --python-script <repository>/tools/start_workspace.py
```

Create synthetic examples outside the repository with Slicer's PythonSlicer
or a development environment containing the pinned requirements:

```sh
python tools/make_synthetic.py /path/outside/repository/Synthetic_dataset
```

These are artificial intensities and identities, not practice anatomy or
anatomical drawing instructions. The source package has the actual proposed
`meniscus_case/1` schema. No real scans are committed.

## Tests

```sh
python -m venv .venv
# Activate this environment, then:
python -m pip install -r requirements-dev.txt
python -m pytest tests packaging/prebuilt/tests --ignore=tests/preparation -q
```

Run the actual editor test inside installed Slicer (with nibabel available):

```text
Slicer --testing --no-splash --ignore-slicerrc --additional-module-paths <repository> --python-script <repository>/tests/slicer_workflow.py
```

Set `MENISCUS_TEST_OUTPUT` to a new empty local directory. The test creates
only synthetic data and writes its results/screenshots there. It drives the
native Paint, Erase and Draw tools through view events, checks oblique planes,
reopens saved files, approves practice versions and exports/reopens ZIP results.
It cannot establish anatomical correctness or replace Windows acceptance.
The scoped app/adapter/packaging suite currently passes 315 tests. Practice-specific run
counts and remaining limits are recorded in [VALIDATION.md](docs/VALIDATION.md);
private MRI evidence is not committed.

In the workspace, Draw closes point-to-point clicks into a filled polygon on the
current acquired slice; Paint/Erase provide touch-ups. For contrast choose
**Window/level** in Image and annotation display, then left-drag. Ctrl+wheel zooms;
right-drag while Draw is active retains the unfinished contour.

The existing-mask correction route passed 337 actual-module checks on two permitted
practice scans, 45 oblique fresh-process restore checks and 65 baseline cold-restore
checks. The dataset preparation session reports all 250 starting masks technically
checked as of 7 November 2026. The final case uses separately documented
compartment attribution through the additive correction-resolution registry,
without changing V20 or the other cases. The full package must include that
registry and its provenance. These predictions and all software-practice outputs
remain unaccepted research annotations until the required expert review.

## Repository and release

Source is stored in the public repository
[mssai0303/meniscus-annotator](https://github.com/mssai0303/meniscus-annotator).
No dataset or annotation is uploaded. Windows review installers are retained
separately from source; the current candidate does not replace the shared
installer or constitute an accepted reader release.
Production releases require actual Windows acceptance. Installer assets remain
separate from the source tree and never include participant data.
Tags identify software versions; every checkpoint records `app_version` and
runtime details. Keep one accepted version for an annotation batch.
