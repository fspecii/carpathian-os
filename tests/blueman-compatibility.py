#!/usr/bin/env python3
"""Blueman compatibility transform fixtures; never touch installed packages."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'integration/carpatic/compatibility/blueman-passkey.py'
spec = importlib.util.spec_from_file_location('blueman_compatibility_fixture', SCRIPT)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def source(filter_text, connection):
    return ('class Agent:\n    def dialog(self):\n' + filter_text +
            '        if is_numeric:\n' + connection + '\n        return pin_entry\n')


class Transform(unittest.TestCase):
    def setUp(self):
        self.original = source(compat.OLD_FILTER, compat.OLD_CONNECT)

    def test_supported_transform_preserves_surrounding_source_and_compiles(self):
        result = compat.transform(self.original)
        self.assertEqual(result, source(compat.NEW_FILTER, compat.NEW_CONNECT))
        self.assertNotIn('insert-text", on_insert_text', result)
        self.assertNotIn('warnings.filterwarnings', result)
        compile(result, '<transformed Blueman fixture>', 'exec')

    def test_supported_result_is_idempotent(self):
        result = compat.transform(self.original)
        self.assertEqual(compat.transform(result), result)

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError): compat.transform('class Unknown: pass\n')

    def test_partial_patch_is_rejected(self):
        for fixture in (source(compat.NEW_FILTER, compat.OLD_CONNECT),
                        source(compat.OLD_FILTER, compat.NEW_CONNECT)):
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                compat.transform(fixture)

    def test_duplicate_original_is_rejected(self):
        with self.assertRaises(ValueError): compat.transform(self.original + self.original)

    def test_duplicate_patched_or_mixed_filter_is_rejected(self):
        patched = compat.transform(self.original)
        for fixture in (patched + patched, patched + compat.OLD_FILTER,
                        self.original + compat.NEW_FILTER):
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                compat.transform(fixture)


if __name__ == '__main__': unittest.main()
