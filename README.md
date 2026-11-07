# Meniscus Annotator 0.1.0

A focused research annotation module and Windows custom-application build for
3D Slicer **5.12.4, revision 34645**. The MRI remains on its complete acquired
grid, including tilted sagittal planes. No model is trained or downloaded.

**Development preview; Windows acceptance is paused for Mac design review.** The actual Slicer desktop
workflow has been exercised on synthetic scans on macOS under Rosetta. A wrapped Windows installer passed hosted installation/import/lifecycle checks;
the redesigned interface has not yet completed Windows acceptance. The real input package is prepared with flat case folders; its full annotation
workflow is not yet accepted. A released anatomical protocol has not been supplied. Do not
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
For an isolated development launch:

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
python -m pytest tests/test_core.py -q
```

Run the actual editor test inside installed Slicer (with nibabel available):

```text
Slicer --no-splash --ignore-slicerrc --additional-module-paths <repository> --python-script <repository>/tests/slicer_workflow.py
```

Set `MENISCUS_TEST_OUTPUT` to a new empty local directory. The test creates
only synthetic data and writes its results/screenshots there. It drives the
native Paint, Erase and Draw tools through view events, checks oblique planes,
reopens saved files, approves practice versions and exports/reopens ZIP results.
It cannot establish anatomical correctness or replace Windows acceptance.

## Repository and release

Source is stored in the owner's private repository
[mssai0303/meniscus-annotator](https://github.com/mssai0303/meniscus-annotator).
No dataset or annotation is uploaded. Built installers belong in private
GitHub Releases after actual Windows acceptance, never in the source tree.
Tags identify software versions; every checkpoint records `app_version` and
runtime details. Keep one accepted version for an annotation batch.
