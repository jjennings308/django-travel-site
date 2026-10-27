"""Render flag-icons' 4:3 flags to the PNGs countries use as their pictures (country-flags plan C1).

Dev only: needs ``cairosvg`` (requirements-dev.txt) and the system cairo library. Production never runs this; it
uses the committed PNGs in ``apps/locations/flags/``. Get the SVGs from npm in a scratch folder, never adding
flag-icons to package.json:

    cd /tmp/scratch && npm pack flag-icons@7.2.3 && tar xzf flag-icons-7.2.3.tgz
    .venv/bin/python scripts/build_flag_pngs.py /tmp/scratch/package

Writes ``apps/locations/flags/<iso2>.png`` (1200 × 900, optimised with Pillow; a flag of 256 colours or fewer as a
lossless palette PNG) for every two-letter flag (the regional ones such as ``gb-eng`` and groupings such as ``eu``
are left out) and copies flag-icons' ``LICENSE`` (MIT) beside them. Prints how many it wrote and the folder's total size.
"""
import io
import shutil
import sys
from pathlib import Path

import cairosvg
from PIL import Image

WIDTH, HEIGHT = 1200, 900
OUT = Path(__file__).resolve().parent.parent / "apps" / "locations" / "flags"


def main(package):
    package = Path(package)
    svgs = sorted(p for p in (package / "flags" / "4x3").glob("*.svg") if len(p.stem) == 2)
    if not svgs:
        sys.exit(f"No flags/4x3/*.svg under {package}")
    OUT.mkdir(parents=True, exist_ok=True)
    for svg in svgs:
        png = cairosvg.svg2png(url=str(svg), output_width=WIDTH, output_height=HEIGHT)
        image = Image.open(io.BytesIO(png)).convert("RGB")
        if image.getcolors(256) is not None:  # 256 colours or fewer: a palette PNG, pixel for pixel the same
            image = image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        image.save(OUT / f"{svg.stem}.png", format="PNG", optimize=True)
    shutil.copyfile(package / "LICENSE", OUT / "LICENSE")
    total = sum(p.stat().st_size for p in OUT.glob("*.png"))
    print(f"Wrote {len(svgs)} flags to {OUT} ({total / 1_000_000:.1f} MB).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
