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

- [Open the checked Mac preview](docs/MAC_PREVIEW.md)
- [Jeff's practical guide](docs/USER_GUIDE.md)
- [Input/output and job contract](docs/CONTRACT.md)
- [Windows reproducible build](docs/WINDOWS.md)
- [Test results and release gaps](docs/VALIDATION.md)
- [Test responsibilities](docs/TEST_PLAN.md)
- [Changelog](CHANGELOG.md)

## Development setup

Use the exact pinned Slicer release from [the official download page](https://download.slicer.org/).
A module is the development route; Jeff's final Windows product will include
its runtime in the custom application's installer. Do not install the PyPI
package named `slicer`; it is unrelated.

For local module development only, use Slicer's Python console once to install
`nibabel==5.3.2` (or install the verified wheel offline using PythonSlicer).
These dependencies are bundled at **build time** in the Windows application;
Jeff will not need Python, pip, a console, a login or runtime downloads.

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
python -m pytest tests/test_core.py tests/test_practice_context.py tests/test_layout_migration.py tests/test_layouts.py tests/test_layout_apply.py -q
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
The scoped app/adapter suite currently passes 151 tests. Practice-specific run
counts and remaining limits are recorded in [VALIDATION.md](docs/VALIDATION.md);
private MRI evidence is not committed.

In the workspace, Draw closes point-to-point clicks into a filled polygon on the
current acquired slice; Paint/Erase provide touch-ups. For contrast choose
**Window/level** in Display and orientation, then left-drag. Right-drag zooms.

The existing-mask correction route passed 337 actual-module checks on two permitted
practice scans, 45 oblique fresh-process restore checks and 65 baseline cold-restore
checks. The updated source package has
249 technically verified starting masks and one explicitly blocked unresolved
case; it is not a complete 250-case correction set. These predictions and all
software-practice outputs remain unaccepted research annotations.

## Repository and release

Source is stored in the owner's private repository
[mssai0303/meniscus-annotator](https://github.com/mssai0303/meniscus-annotator).
No dataset or annotation is uploaded. Built installers belong in private
GitHub Releases after actual Windows acceptance, never in the source tree.
Tags identify software versions; every checkpoint records `app_version` and
runtime details. Keep one accepted version for an annotation batch.
