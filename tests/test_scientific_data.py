"""Integrity checks for the released scientific dataset."""
import hashlib
import json
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]


class ScientificDataTests(unittest.TestCase):
    def test_scientific_files_match_release_fingerprints(self):
        manifest = json.loads((ROOT / 'tests/scientific_data_sha256.json').read_text())
        self.assertEqual(422, len(manifest['files']))
        directories = ('cases', 'evaluation/gold', 'evaluation/t2_contexts', 'evaluation/t3_gold',
                       'tracks/t2/cases', 'tracks/t3/cases', 'references')
        actual = {str(path.relative_to(ROOT)) for name in directories for path in (ROOT/name).rglob('*.json')}
        self.assertEqual(actual, set(manifest['files']))
        for name, expected in manifest['files'].items():
            with self.subTest(path=name):
                value = json.loads((ROOT / name).read_text())
                encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
                self.assertEqual(expected, hashlib.sha256(encoded).hexdigest())


if __name__ == '__main__': unittest.main()
