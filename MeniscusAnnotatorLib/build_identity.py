"""Capture software identity without reading any dataset or user work."""
import hashlib
import json
from pathlib import Path
import subprocess


def capture_source_identity(module_root=None):
    root = Path(module_root) if module_root else Path(__file__).resolve().parents[1]
    candidates = [root / 'MeniscusAnnotator.py']
    candidates += sorted((root / 'MeniscusAnnotatorLib').rglob('*'))
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in candidates if p.is_file() and '__pycache__' not in p.parts
              and p.suffix != '.pyc'}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = {'application_source_sha256': digest, 'application_files_sha256': hashes,
                'application_commit': None, 'application_source_dirty': None,
                'identity_scope': 'Source files at module initialization; no anatomical or platform acceptance'}
    # Installed module is under lib/Slicer-<version>/qt-scripted-modules.
    for parent in [root, *list(root.parents)[:3]]:
        receipt = parent / 'BUILD-IDENTITY.json'
        if not receipt.is_file():
            continue
        try:
            recorded = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        matches = recorded.get('application_source_sha256') == digest
        identity['packaged_source_matches'] = matches
        if matches:
            identity['application_commit'] = recorded.get('application_commit')
            identity['application_source_dirty'] = recorded.get('application_source_dirty')
        return identity
    if (root / '.git').exists():
        try:
            result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                    capture_output=True, text=True, timeout=3, check=True)
            identity['application_commit'] = result.stdout.strip()
            result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'],
                                    capture_output=True, text=True, timeout=3, check=True)
            identity['application_source_dirty'] = bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return identity
