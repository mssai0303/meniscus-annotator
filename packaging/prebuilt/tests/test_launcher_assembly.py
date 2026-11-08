"""Small fake-runtime assembly checks; no downloads or executable launch."""
import importlib.util
import json
from pathlib import Path
import re
import zipfile


def test_every_real_test_application_has_its_canonical_launcher_settings(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('prepare_under_test', repo / 'packaging/prebuilt/prepare.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    runtime = tmp_path / 'Fake official runtime'
    for name in ('bin', 'include', 'lib', 'libexec', 'share'):
        (runtime / name).mkdir(parents=True)
    (runtime / 'lib/Slicer-5.12/qt-scripted-modules').mkdir(parents=True)
    (runtime / 'share/Slicer-5.12').mkdir(parents=True)
    (runtime / 'Slicer.exe').write_bytes(b'SYNTHETIC LAUNCHER; NOT EXECUTABLE')
    (runtime / 'bin/SlicerApp-real.exe').write_bytes(b'SYNTHETIC APPLICATION; NOT EXECUTABLE')
    (runtime / 'bin/SlicerLauncherSettings.ini').write_text(
        '[Application]\npath=<APPLAUNCHER_DIR>/bin/SlicerApp-real.exe\narguments=\nname=Slicer\n[EnvironmentVariables]\n', encoding='utf-8')
    site = runtime / 'lib/Python/Lib/site-packages'
    for name, version in (('numpy', '2.4.6'), ('packaging', '26.2'), ('typing_extensions', '4.15.0')):
        metadata = site / (name + '-' + version + '.dist-info')
        metadata.mkdir(parents=True)
        (metadata / 'METADATA').write_text('Version: ' + version + '\n', encoding='utf-8')
    cache = tmp_path / 'cache'; cache.mkdir()
    wheel = cache / 'nibabel-5.3.2-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('nibabel/__init__.py', '# Synthetic packaging placeholder, never imported\n')
    installer = tmp_path / 'fake-installer.exe'; installer.write_bytes(b'NOT EXECUTABLE')
    monkeypatch.setattr(prepare, 'verified_download', lambda item, target: Path(target))
    output = tmp_path / 'Payload'
    prepare.prepare(runtime, installer, output, cache)
    manifest = json.loads((output / 'distribution.json').read_text(encoding='utf-8'))
    # qSlicerCoreApplication derives the canonical settings name from its
    # App-real executable, not from whichever action alias launched it.
    for real in output.glob('bin/Meniscus*App-real.exe'):
        base = real.name.removesuffix('App-real.exe')
        settings = output / 'bin' / (base + 'LauncherSettings.ini')
        assert settings.is_file(), base
        assert (output / (base + '.exe')).is_file(), base
        assert settings.relative_to(output).as_posix() in manifest['files_sha256']
    assert (output / 'MeniscusAnnotatorTest.exe').read_bytes() == (runtime / 'Slicer.exe').read_bytes()
    assert 'name=MeniscusAnnotatorTest\n' in (output / 'bin/MeniscusAnnotatorTestLauncherSettings.ini').read_text(encoding='utf-8')

    canonical = (output / 'bin/MeniscusAnnotatorTestLauncherSettings.ini').read_text(encoding='utf-8')
    assert 'MENISCUS_TEST_ACTION=' not in canonical
    for alias, action in [('Examples', 'create'), ('CorrectionChecks', 'correction'), ('CorrectionResumeCheck', 'correction-resume'),
                          ('DrawChecks', 'draw'), ('DrawResumeCheck', 'draw-resume'), ('DrawLayoutChecks', 'draw-layout'),
                          ('RegionsChecks', 'regions'), ('RegionsResumeCheck', 'regions-resume'),
                          ('RegionsLegacyCheck', 'regions-legacy')]:
        config = (output / ('bin/MeniscusAnnotator' + alias + 'LauncherSettings.ini')).read_text(encoding='utf-8')
        assert 'MENISCUS_TEST_ACTION=' + action + '\n' in config
    for relative in ('tests/slicer_draw_workflow.py', 'tests/slicer_regions_workflow.py', 'tests/draw_fixture.py'):
        assert (output / 'TestKit' / relative).read_bytes() == (repo / relative).read_bytes()
        assert 'TestKit/' + relative in manifest['files_sha256']
    assert not (output / 'TestKit/MeniscusAnnotator.py').exists()
    assert not (output / 'bin/opengl32.dll').exists()  # diagnostic alias is never shipped
    assert (output / 'ReaderGuide.html').read_bytes() == (repo / 'docs/QUICK_START.html').read_bytes()
    assert 'ReaderGuide.html' in manifest['files_sha256']
    guide_text = (output / 'UserGuide.txt').read_text(encoding='utf-8')
    references = set(re.findall(r'!\[[^\]]*\]\(([^)]+)\)', guide_text))
    assert references == {'GuideImages/annotation-workflow.png', 'GuideImages/draw-unfinished.png', 'GuideImages/regional-workflow.png'}
    for relative in references:
        target = output / relative
        source = repo / 'docs/images' / target.name
        assert target.is_file() and target.read_bytes() == source.read_bytes()
        assert manifest['files_sha256'][relative] == prepare.digest(source)
    for name in ('REGIONAL_CONTRACT.md', 'REGIONAL_READER.md'):
        assert (output / name).read_bytes() == (repo / 'docs' / name).read_bytes()
        assert manifest['files_sha256'][name] == prepare.digest(repo / 'docs' / name)
    example = repo / 'tools/read_regional_annotation.py'
    assert (output / 'Examples' / example.name).read_bytes() == example.read_bytes()
    assert manifest['files_sha256']['Examples/' + example.name] == prepare.digest(example)

    test_defaults = (output / 'share/Slicer-5.12/MeniscusAnnotatorTestDefaultSettings.ini').read_text(encoding='utf-8')
    assert 'HomeModule=MeniscusAnnotator\n' in test_defaults
    assert 'HomeModule=\n' not in test_defaults
