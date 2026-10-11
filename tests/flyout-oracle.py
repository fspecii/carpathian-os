#!/usr/bin/env python3
"""Focused host checks for first-visible flyout classification."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent / 'debug'))
from flyout_oracle import classify


class FirstPresentation(unittest.TestCase):
    def test_hidden_and_publication_lag(self):
        self.assertEqual(classify(0, [1, 1], 1, 2, False), 'hidden')
        self.assertEqual(classify(1, [1, 1], 1, 2, False), 'pending-presentation')
        self.assertEqual(classify(1, [2, 2], 1, 2, False), 'visible')

    def test_foreign_first_frame_is_rejected(self):
        for pixels in ([3, 3], [1, 2], [2, 3]):
            with self.subTest(pixels=pixels), self.assertRaises(AssertionError):
                classify(1, pixels, 1, 2, False)

    def test_hidden_corruption_and_fractional_opacity(self):
        for opacity, pixels in ((0, [1, 3]), (.5, [2, 2])):
            with self.subTest(opacity=opacity), self.assertRaises(AssertionError):
                classify(opacity, pixels, 1, 2, False)

    def test_post_visibility_regression_is_rejected(self):
        for pixels in ([1, 1], [2, 3]):
            with self.subTest(pixels=pixels), self.assertRaises(AssertionError):
                classify(1, pixels, 1, 2, True)
        self.assertEqual(classify(1, [2, 2], 1, 2, True), 'visible')


if __name__ == '__main__':
    unittest.main()
