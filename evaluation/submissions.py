"""Batch registry for case submissions."""
import json
from pathlib import Path


def load_batch(path):
    path = Path(path)
    if path.is_dir():
        rows = [json.loads(p.read_text()) for p in sorted(path.glob('*.json'))]
    else:
        registry = json.loads(path.read_text())
        rows = registry.get('submissions') if isinstance(registry, dict) else registry
        if not isinstance(rows, list): raise ValueError('Batch registry requires a submissions array')
        expanded = []
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Submission entries must be objects')
            if 'submission' in row:
                target = Path(row['submission']); target = target if target.is_absolute() else path.parent / target
                value = json.loads(target.read_text())
                if row.get('case_id', value.get('case_id')) != value.get('case_id'): raise ValueError('Registry case_id mismatch')
                expanded.append(value)
            else: expanded.append(row)
        rows = expanded
    result = {}
    for row in rows:
        cid = row.get('case_id')
        if not isinstance(cid, str) or not cid or cid in result: raise ValueError('Case IDs must be distinct')
        result[cid] = row
    return result
