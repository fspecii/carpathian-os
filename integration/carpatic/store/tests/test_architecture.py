"""Architecture install guards: no network, package or container operations."""
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import carpatic_store as store
import carpatic_ai as ai

class Architecture(unittest.TestCase):
    def setUp(self):
        self.catalog = store.Catalog(str(ROOT / 'catalog'))
        with (ROOT / 'ai/tools.toml').open('rb') as source:
            self.tools = {t['id']: t for t in tomllib.load(source)['tool']}

    def test_arm_rejects_curated_x86_before_backend(self):
        with patch.object(store.platform, 'machine', return_value='aarch64'), patch.object(store, 'compat_cmd') as compat, patch.object(ai, 'install') as install_ai:
            for ident in ('chrome', 'codex', 'opencode', 'goose'):
                with self.subTest(ident=ident), self.assertRaisesRegex(store.StoreError, 'unavailable on aarch64'):
                    store.install(self.catalog.resolve(ident))
            compat.assert_not_called(); install_ai.assert_not_called()

    def test_direct_ai_force_and_dict_rejected_before_state_or_download(self):
        with patch.object(store.platform, 'machine', return_value='arm64'), patch.object(ai, 'get_tool', side_effect=lambda ident: self.tools[ident]), patch.object(ai, 'is_installed') as installed, patch.object(ai, '_github') as download:
            for ident in ('codex', 'opencode', 'goose'):
                for recipe in (ident, self.tools[ident]):
                    with self.assertRaisesRegex(store.StoreError, 'unavailable on aarch64'):
                        ai.install(recipe, force=True)
            with self.assertRaisesRegex(store.StoreError, 'unavailable on aarch64'):
                ai.update('codex')
            installed.assert_not_called(); download.assert_not_called()

    def test_direct_compat_url_and_missing_metadata_still_rejected(self):
        with patch.object(store.platform, 'machine', return_value='aarch64'), patch.object(store, 'compat_cmd') as compat:
            url = self.catalog.resolve('chrome')['pkg']
            with self.assertRaisesRegex(store.StoreError, 'built for x86_64'):
                store.install(self.catalog.resolve('compat:' + url))
            recipe = dict(self.tools['opencode']); recipe.pop('architectures')
            with self.assertRaisesRegex(store.StoreError, 'built for x86_64'):
                ai.install(recipe)
            compat.assert_not_called()

    def test_native_arm_backend_unchanged(self):
        with patch.object(store.platform, 'machine', return_value='aarch64'), patch.object(store, '_apk', return_value=0) as apk:
            store.install(self.catalog.resolve('firefox'))
            apk.assert_called_once()
        with patch.object(store.platform, 'machine', return_value='aarch64'), patch.object(ai, 'is_installed', return_value=True):
            self.assertEqual(ai.install(self.tools['ollama']), 'already')

    def test_x86_alias_and_supported_recipes_unchanged(self):
        with patch.object(store.platform, 'machine', return_value='AMD64'), patch.object(ai, 'is_installed', return_value=True):
            for ident in ('codex', 'opencode', 'goose'):
                store.require_architecture(self.catalog.resolve(ident))
                self.assertEqual(ai.install(self.tools[ident]), 'already')
            store.require_architecture(self.catalog.resolve('chrome'))

if __name__ == '__main__': unittest.main()
