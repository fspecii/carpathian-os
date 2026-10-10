#!/usr/bin/env python3
"""Pure seam classifier controls: no X11, GTK, VM or capture operations."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('seam', Path(__file__).parent/'debug/seam_segments.py')
seam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seam)
CHROME, BODY, BACK = [48, 35, 36], [37, 169, 223], [7, 9, 13]


def classify(gap):
    rows = [CHROME]*20 + gap + [BODY]*20
    return seam.classify_seam(rows, 20+len(gap), CHROME, BODY)


class Controls(unittest.TestCase):
    def test_actual_exact_capture_band(self):
        band = [[44,90,112],[39,156,205],[39,156,205],[39,156,205],[38,159,209]]
        r=classify(band)
        self.assertEqual(r['gap'],5)
        self.assertTrue(r['interpolated_bridge'])
        self.assertFalse(r['failed'])

    def test_real_five_pixel_background_hole_fails(self):
        r=classify([BACK]*5)
        self.assertEqual(r['gap'],5)
        self.assertTrue(r['failed'])

    def test_missing_caption_fails(self):
        rows=[BACK]*70+[BODY]*20
        r=seam.classify_seam(rows,70,CHROME,BODY)
        self.assertEqual(r['gap'],999)
        self.assertTrue(r['failed'])

    def test_nonmonotonic_band_fails(self):
        self.assertTrue(classify([[39,156,205],[44,90,112],[39,156,205],[39,156,205],[38,159,209]])['failed'])

    def test_unrelated_nearby_color_fails(self):
        self.assertTrue(classify([[44,90,116]]*5)['failed'])

    def test_long_blended_separation_stays_failed(self):
        self.assertTrue(classify([[44,90,112]]*20)['failed'])

    def test_no_body_anchor_does_not_qualify(self):
        rows=[CHROME]*20+[[44,90,112]]*5+[BACK]*20
        self.assertTrue(seam.classify_seam(rows,25,CHROME,BODY)['failed'])

    def test_legacy_zero_and_four_pixel_limits_preserved(self):
        self.assertFalse(classify([])['failed'])
        self.assertFalse(classify([BACK]*4)['failed'])


if __name__=='__main__':unittest.main()
