"""Source archive validation without Git metadata or third-party packages."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import check_repository
from scripts.build_release import source_files

ROOT = Path(__file__).resolve().parents[1]


class RepositoryScanTests(unittest.TestCase):
    def test_non_git_scan_ignores_local_runtime_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(ROOT / '.gitignore', root / '.gitignore')
            (root / 'source.py').write_text('"""Source file."""\n')
            for directory in ('documents', 'submissions', 'results', 'dist', '.venv', '.cache',
                              'prepared_documents', 'source_documents', '__pycache__', 'nested/__pycache__'):
                path = root / directory / 'local.pdf'
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'local artifact')
            (root / '.DS_Store').write_bytes(b'local artifact')
            (root / 'source.pyc').write_bytes(b'local artifact')
            output = io.StringIO()
            with patch.object(check_repository, 'ROOT', root), patch.object(sys, 'argv', ['check_repository.py']), \
                    patch.object(check_repository.subprocess, 'check_output') as git, contextlib.redirect_stdout(output):
                self.assertEqual(0, check_repository.main())
            git.assert_not_called()
            self.assertEqual({'files_checked': 2, 'issues': []}, json.loads(output.getvalue()))

    def test_tracked_option_still_requires_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(check_repository, 'ROOT', root), \
                    patch.object(sys, 'argv', ['check_repository.py', '--tracked']), \
                    patch.object(check_repository.subprocess, 'check_output',
                                 side_effect=subprocess.CalledProcessError(128, ['git'])) as git:
                with self.assertRaises(subprocess.CalledProcessError):
                    check_repository.main()
            git.assert_called_once_with(['git', 'ls-files', '-z'], cwd=root)


class ReleaseArchiveTests(unittest.TestCase):
    @unittest.skipIf(os.environ.get('EVISYNTH_ARCHIVE_TEST_CHILD') == '1',
                     'The parent test runs this suite in the extracted archive.')
    def test_built_archive_passes_all_checks_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; archive = root / 'release.zip'
            # Build from a temporary source tree so tests do not rewrite the checkout manifest.
            for path in source_files():
                target = source / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            completed = subprocess.run([sys.executable, '-S', 'scripts/build_release.py', '--output', str(archive)],
                                       cwd=source, text=True, capture_output=True)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                bundle.extractall(root / 'extracted')
            extracted = root / 'extracted/EviSynth-Bench'
            self.assertFalse((extracted / '.git').exists())
            env = dict(os.environ, EVISYNTH_ARCHIVE_TEST_CHILD='1')
            for command in (['scripts/check_repository.py'], ['scripts/validate_release.py'],
                            ['-m', 'unittest', 'discover', '-s', 'tests', '-v']):
                with self.subTest(command=command):
                    completed = subprocess.run([sys.executable, '-S', *command], cwd=extracted,
                                               env=env, text=True, capture_output=True)
                    self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
