"""Assemble a data-free Windows payload from a verified official runtime.

Runs on Python 3.9+ on the maintainer's host. It never executes Windows binaries.
Only source code, official runtime and locked dependency wheels enter the payload.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOCK = json.loads((HERE / 'dependencies.json').read_text(encoding="utf-8"))

def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def verified_download(item, target):
    target = Path(target)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.pending')
        urllib.request.urlretrieve(item['url'], temporary)
        temporary.replace(target)
    algorithm = 'sha512' if 'sha512' in item else 'sha256'
    if digest(target, algorithm) != item[algorithm]:
        raise ValueError('Dependency checksum mismatch: ' + target.name)
    return target

def nsis_literal(value):
    # Source file names from archives are not allowed to become installer commands.
    if any(c in value for c in ('"', '\n', '\r', '\0')):
        raise ValueError('Unsupported installer filename')
    return value.replace('$', '$$')

def prepare(runtime, installer, output, cache):
    verified_download(LOCK['slicer'], installer)
    if output.exists():
        raise ValueError('Payload output already exists; choose a new folder. Existing work is preserved.')
    if not (runtime / 'Slicer.exe').is_file() or not (runtime / 'bin' / 'SlicerApp-real.exe').is_file():
        raise ValueError('Expected extracted Slicer runtime is missing')
    cache.mkdir(parents=True, exist_ok=True)
    wheel = verified_download(LOCK['nibabel'], cache / 'nibabel-5.3.2-py3-none-any.whl')
    output.mkdir(parents=True)
    # Only expected top-level runtime payloads; omit NSIS extraction plugins/uninstaller.
    for name in ['Slicer.exe', 'bin', 'include', 'lib', 'libexec', 'share']:
        source = runtime / name
        if source.is_dir():
            shutil.copytree(source, output / name)
        else:
            shutil.copy2(source, output / name)
    original_files = {str(f.relative_to(output)).replace('\\', '/'): digest(f)
                      for f in output.rglob('*') if f.is_file()}
    module_dir = output / 'lib' / 'Slicer-5.12' / 'qt-scripted-modules'
    shutil.copy2(REPO / 'MeniscusAnnotator.py', module_dir / 'MeniscusAnnotator.py')
    shutil.copytree(REPO / 'MeniscusAnnotatorLib', module_dir / 'MeniscusAnnotatorLib',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    site = output / 'lib' / 'Python' / 'Lib' / 'site-packages'
    for glob, expected in [('numpy-*.dist-info', '2.4.6'), ('packaging-*.dist-info', '26.2'), ('typing_extensions-*.dist-info', '4.15.0')]:
        candidates = list(site.glob(glob))
        if len(candidates) != 1 or ('Version: ' + expected + '\n') not in (candidates[0] / 'METADATA').read_text(encoding="utf-8"):
            raise ValueError('Official runtime dependency differs from the lock: ' + glob)
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or info.filename.endswith('/'):
                if info.filename.endswith('/'):
                    continue
                raise ValueError('Unsafe wheel path')
            target = site.joinpath(*path.parts)
            if target.exists():
                raise ValueError('Refusing to overwrite runtime dependency: ' + info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    # Official documented Slicelet launcher cloning: separate settings namespace.
    # Upstream executables remain byte-for-byte unchanged.
    shutil.copy2(output / 'Slicer.exe', output / 'MeniscusAnnotator.exe')
    shutil.copy2(output / 'bin' / 'SlicerApp-real.exe', output / 'bin' / 'MeniscusAnnotatorApp-real.exe')
    config = (output / 'bin' / 'SlicerLauncherSettings.ini').read_text(encoding="utf-8")
    config = config.replace('/bin/SlicerApp-real.exe', '/bin/MeniscusAnnotatorApp-real.exe')
    config = re.sub(r'^arguments=$', 'arguments=--no-splash --disable-cli-modules --modules-to-ignore Welcome', config, count=1, flags=re.M)
    config = re.sub(r'^name=Slicer$', 'name=MeniscusAnnotator', config, count=1, flags=re.M)
    config = config.replace('[EnvironmentVariables]', '[EnvironmentVariables]\nPYTHONDONTWRITEBYTECODE=1\nSLICERRC=<APPLAUNCHER_DIR>/Bootstrap.py')
    (output / 'bin' / 'MeniscusAnnotatorLauncherSettings.ini').write_text(config, encoding="utf-8")
    shutil.copy2(HERE / 'Bootstrap.py', output / 'Bootstrap.py')
    shutil.copy2(HERE / 'RuntimeCheck.py', output / 'RuntimeCheck.py')
    shutil.copy2(HERE / 'WorkflowShell.py', output / 'WorkflowShell.py')
    shutil.copy2(REPO / 'packaging' / 'Applications' / 'MeniscusAnnotatorApp' / 'Resources' / 'DesktopIcon.ico', output / 'MeniscusAnnotator.ico')
    defaults = output / 'share' / 'Slicer-5.12' / 'MeniscusAnnotatorDefaultSettings.ini'
    defaults.write_text('[Modules]\nHomeModule=MeniscusAnnotator\n[Extensions]\nAutoUpdateCheck=false\nAutoUpdateInstall=false\n[ApplicationUpdate]\nAutoUpdateCheck=false\n[ApplicationUpdates]\nEnabled=false\n', encoding="utf-8")
    # Whitelist procedural fixtures and the maintained native suite only. No
    # source checkout/application copy is placed in TestKit.
    kit = output / 'TestKit'
    for relative in ('tests/slicer_workflow.py', 'tests/slicer_export_dialog.py', 'tools/make_synthetic.py'):
        destination = kit / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, destination)
    (kit / 'tools' / '__init__.py').write_text('"""Procedural synthetic fixtures only."""\n', encoding='utf-8')
    (kit / 'tests' / '__init__.py').write_text('"""Synthetic software tests only."""\n', encoding='utf-8')
    for name in ('make_correction_synthetic.py', 'CorrectionWorkflow.py'):
        shutil.copy2(HERE / name, kit / name)
    shutil.copy2(HERE / 'RunInstalledTests.py', kit / 'RunInstalledTests.py')
    shutil.copy2(HERE / 'SyntheticTestKit.txt', kit / 'README.txt')
    shutil.copy2(HERE / 'RunSyntheticChecks.ps1', kit / 'RunSyntheticChecks.ps1')
    shutil.copy2(output / 'bin' / 'SlicerApp-real.exe', output / 'bin' / 'MeniscusAnnotatorTestApp-real.exe')
    # The real application derives this canonical settings filename from
    # MeniscusAnnotatorTestApp-real.exe, even when an action alias launched it.
    # Both the canonical pair and action aliases must exist.
    for stem, action in (('MeniscusAnnotatorTest', 'workflow'), ('MeniscusAnnotatorChecks', 'workflow'), ('MeniscusAnnotatorResumeCheck', 'resume'), ('MeniscusAnnotatorExamples', 'create'), ('MeniscusAnnotatorCorrectionChecks', 'correction'), ('MeniscusAnnotatorCorrectionResumeCheck', 'correction-resume')):
        shutil.copy2(output / 'Slicer.exe', output / (stem + '.exe'))
        test_config = config.replace('/bin/MeniscusAnnotatorApp-real.exe', '/bin/MeniscusAnnotatorTestApp-real.exe')
        test_config = test_config.replace('name=MeniscusAnnotator\n', 'name=MeniscusAnnotatorTest\n')
        test_config = test_config.replace('SLICERRC=<APPLAUNCHER_DIR>/Bootstrap.py',
                                          'SLICERRC=<APPLAUNCHER_DIR>/TestKit/RunInstalledTests.py\nMENISCUS_TEST_ACTION=' + action)
        # Native Slicer reloads this canonical INI after the action alias.
        # It must not overwrite the alias's selected test action.
        if stem == 'MeniscusAnnotatorTest':
            test_config = test_config.replace('\nMENISCUS_TEST_ACTION=' + action, '')
        if action == 'create':
            test_config = test_config.replace('arguments=--no-splash', 'arguments=--no-main-window --no-splash')
        (output / 'bin' / (stem + 'LauncherSettings.ini')).write_text(test_config, encoding='utf-8')
    # Keep the test profile from constructing the reader widget before the suite
    # redirects its QSettings; production home remains MeniscusAnnotator.
    test_defaults = output / 'share' / 'Slicer-5.12' / 'MeniscusAnnotatorTestDefaultSettings.ini'
    test_defaults.write_text('[Modules]\nHomeModule=\n[Extensions]\nAutoUpdateCheck=false\nAutoUpdateInstall=false\n[ApplicationUpdate]\nAutoUpdateCheck=false\n[ApplicationUpdates]\nEnabled=false\n', encoding='utf-8')
    license_dir = output / 'share' / 'MeniscusAnnotator' / 'licenses'
    license_dir.mkdir(parents=True)
    for source in (REPO / 'packaging' / 'licenses').glob('*'):
        shutil.copy2(source, license_dir / source.name)
    shutil.copy2(REPO / 'LICENSE', license_dir / 'MeniscusAnnotator-Apache-2.0.txt')
    shutil.copy2(REPO / 'packaging' / 'TEMPLATE_NOTICE.txt', license_dir / 'TEMPLATE_NOTICE.txt')
    (output / 'README-FIRST.txt').write_text('Meniscus Annotator 0.1.0\nBased on official 3D Slicer 5.12.4 r34645.\nOpen Meniscus Annotator from the Start menu, then Open dataset.\nDo not edit files in this installation directory. Saved work and exports live in your chosen local work/results folders.\nThis wrapped distribution retains upstream Slicer branding and runtime version. It is not a custom-compiled Slicer application.\n', encoding="utf-8")
    guide = REPO / 'docs' / 'USER_GUIDE.md'
    if guide.exists():
        (output / 'UserGuide.txt').write_text(guide.read_text(encoding="utf-8").replace('images/annotation-workflow.png', 'GuideImages/annotation-workflow.png'), encoding="utf-8")
    shutil.copy2(REPO / 'docs' / 'QUICK_START.html', output / 'ReaderGuide.html')
    image = REPO / 'docs' / 'images' / 'annotation-workflow.png'
    if image.exists():
        (output / 'GuideImages').mkdir()
        shutil.copy2(image, output / 'GuideImages' / image.name)
    for name, sha in original_files.items():
        if digest(output / name) != sha:
            raise ValueError('Original runtime file changed: ' + name)
    try:
        revision = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain', '--untracked-files=normal'], text=True).strip())
    except Exception:
        revision = 'unrecorded-local-source'
        dirty = True
    source_files = {p.relative_to(module_dir).as_posix(): digest(p)
                    for p in sorted(module_dir.rglob('*'))
                    if p.is_file() and (p.name == 'MeniscusAnnotator.py' or 'MeniscusAnnotatorLib' in p.parts)}
    source_hash = hashlib.sha256(json.dumps(source_files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = {'application_version': '0.1.0', 'application_commit': revision,
                'application_source_dirty': dirty, 'application_source_sha256': source_hash,
                'application_files_sha256': source_files}
    (output / 'BUILD-IDENTITY.json').write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
    files = {str(f.relative_to(output)).replace('\\', '/'): digest(f)
             for f in sorted(output.rglob('*')) if f.is_file()}
    manifest = {'schema_version': 'meniscus_distribution/1', 'application_version': '0.1.0',
                **identity, 'route': LOCK['route'],
                'slicer_installer_sha512': LOCK['slicer']['sha512'],
                'original_runtime_files_unchanged': len(original_files),
                'files_sha256': files,
                'scope': 'Payload assembly and byte-integrity checks only; no Windows execution or anatomical validation implied.'}
    (output / 'distribution.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding="utf-8")
    # Delete only known installed files. Unrelated user files survive uninstall.
    names = sorted([*files, 'distribution.json'], reverse=True)
    commands = ['Delete "$INSTDIR\\' + nsis_literal(name.replace('/', '\\')) + '"' for name in names]
    directories = sorted({str(f.relative_to(output)).replace('\\', '/') for f in output.rglob('*') if f.is_dir()}, key=lambda n: (n.count('/'), n), reverse=True)
    commands += ['Call un.ReleaseRuntimeGuards']
    commands += ['RMDir "$INSTDIR\\' + nsis_literal(name.replace('/', '\\')) + '"' for name in directories]
    (output.parent / 'uninstall-files.nsh').write_text('\n'.join(commands) + '\n', encoding="utf-8")
    return {'files': len(files) + 1, 'bytes': sum(f.stat().st_size for f in output.rglob('*') if f.is_file()), 'original_runtime_files_unchanged': len(original_files)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-extracted', type=Path, required=True)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.runtime_extracted.resolve(), args.installer.resolve(), args.output.resolve(), args.cache.resolve()), indent=2))
