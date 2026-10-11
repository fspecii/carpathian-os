# Installer boot artwork

`boot-background.svg` and `boot-splash.svg` reuse the exact two public panel
mountain paths from `integration/carpatic/panel/assets/branding/carpathian-os.svg`.
The light mint variant uses the established boot-menu palette for contrast.
The Carpathian OS wordmark is outlined DejaVu Sans regular, with license in
`BOOT-FONT-LICENSE.txt`; no runtime font lookup is needed to display it.

`boot-render-provenance.json` records the logo, font, renderer and output hashes
and Cairo/ImageMagick versions. Reproduce on a developer machine with those
versions and font bytes using:

```
/usr/bin/python3 integration/carpatic/installer-branding/assets/render-boot.py
python3 tests/iso-boot-branding.py
```

The renderer requires Pycairo, Fontconfig and ImageMagick only for regeneration.
ISO assembly uses the committed RGB8, noninterlaced PNG files directly. Review
SVG/PNG differences and update provenance together if any rendering dependency
changes. No timestamps, text chunks, external images or fonts are embedded in
the PNG output. Quiet lower regions preserve inherited menu placement,
countdown and keyboard help. Boot paths and identifiers retain compatibility.
