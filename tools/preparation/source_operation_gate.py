"""Shared metadata-only restriction gate before extraction or source-image read."""
import csv
import hashlib
import json
from pathlib import Path

def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def require_source_permission(root, rows):
    root=Path(root)
    record=json.loads((root/'results/restriction_gate.json').read_text())
    permitted_path=root/'private/PRIVATE_restriction_permitted_participants.csv'
    if not record.get('locked_manifest_hash_valid') or file_sha256(permitted_path)!=record['output_sha256']:
        raise ValueError('restriction_gate_integrity_failed')
    # Refuse a stale gate if any frozen restriction source has changed since the
    # original metadata-only check. These are named metadata, never images.
    for path,digest in record['hashes'].items():
        if file_sha256(path)!=digest:
            raise ValueError('restriction_source_version_changed')
    with permitted_path.open(newline='') as f:
        allowed={r['participant_id'] for r in csv.DictReader(f)}
    for row in rows:
        participant=str(row['participant_id'])
        study_value=int(hashlib.sha256(('slice-placement-v1:'+participant).encode()).hexdigest()[:12],16)/float(16**12)
        if participant not in allowed or study_value>=.70:
            raise ValueError('source_permission_gate_failed')
