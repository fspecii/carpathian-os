#!/usr/bin/env python3
"""Exercise style-pack provisioning from the filtered live payload archive."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('arm_live', ROOT / 'scripts/prepare-arm64-live.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Payload(unittest.TestCase):
    def test_packaged_stylepacks_install_and_missing_document_control(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / 'source/integration/carpatic/stylepacks'
            shutil.copytree(ROOT / 'integration/carpatic/stylepacks', source, symlinks=True)
            (source / 'development-notes.md').write_text('Not runtime documentation')
            (source / 'incidental-build').write_bytes(b'\x7fELFnot-a-shipping-payload')
            package = work / 'payload.tar.gz'
            module.archive(work / 'source', package)
            extracted = work / 'extracted'
            with tarfile.open(package) as archive:
                names = archive.getnames()
                self.assertIn('integration/carpatic/stylepacks/RESEARCH.md', names)
                self.assertNotIn('integration/carpatic/stylepacks/development-notes.md', names)
                self.assertNotIn('integration/carpatic/stylepacks/incidental-build', names)
                archive.extractall(extracted, filter='data')
            component = extracted / 'integration/carpatic/stylepacks'
            installed = work / 'installed'
            result = subprocess.run(['sh', str(component / 'install.sh')],
                                    env={**os.environ, 'DESTDIR': str(installed),
                                         'SHARE_DIR': str(installed / 'usr/local/share/carpatic/configurator')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = installed / 'usr/local/share/carpatic/stylepacks/RESEARCH.md'
            self.assertEqual(document.read_bytes(), (source / 'RESEARCH.md').read_bytes())
            (component / 'RESEARCH.md').unlink()
            result = subprocess.run(['sh', str(component / 'install.sh')],
                                    env={**os.environ, 'DESTDIR': str(work / 'negative'),
                                         'SHARE_DIR': str(work / 'negative/usr/local/share/carpatic/configurator')},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('RESEARCH.md', result.stderr)


if __name__ == '__main__':
    unittest.main()
