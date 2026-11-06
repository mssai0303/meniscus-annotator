"""Byte-for-byte verification through a separate standard Python reader."""
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
manifest = json.loads((root / 'distribution.json').read_text())
for name, expected in manifest['files_sha256'].items():
    file = root / name
    h = hashlib.sha256()
    with file.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    if h.hexdigest() != expected:
        raise ValueError('Installed file differs from payload: ' + name)
print(json.dumps({'passed': True, 'files': len(manifest['files_sha256']), 'scope': 'Installed bytes only'}, indent=2))
