#!/usr/bin/env python3
"""
pixelate.py - rebuild assets/pixel/ from assets/img-source/.

Three stages, per the proper-pixel-art README's own recipe for real
photographs (the tool recovers a grid from art that is already pixel-art
shaped; it is not a photo pixelator on its own):

  1. Pillow intermediate. Crop to the subject, stretch contrast, area-average
     down to the target block grid, then upscale by nearest neighbour so the
     blocks are hard and exactly aligned. That is the grid ppa expects.
  2. ppa. Run the CLI on the intermediate with -w (the block size we just
     created, so mesh detection cannot drift), -c and -s.
  3. Palette lock. ppa -c picks its own colours, so every output is remapped
     onto a generated ramp: NEUTRAL_STEPS shades of grey plus RED_STEPS
     shades of the page's --red. Quantisation happens at TRUE pixel
     resolution, before the final nearest-neighbour upscale, because
     dithering after the upscale would scatter dots inside each block and
     destroy the pixel grid.

The page is a light scheme with white paper and no dark-mode block, so there
is one palette and two files per image: the desktop display scale and the
phone one. Every display width is grid_width * an integer scale, so the blocks
always land on whole CSS pixels.

Images are exposed so the subject reads as DARK marks on white. On a white
page a high-key photograph dissolves, so black_point / white_point pull the
useful part of each histogram down into the dark half of the ramp rather than
leaving its mass in the tints.

Usage:  python tools/pixelate.py [--only SLUG] [--keep-intermediate]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "assets" / "img-source"
OUT_DIR = ROOT / "assets" / "pixel"
WORK_DIR = ROOT / "assets" / "pixel-work"

# ---------------------------------------------------------------------------
# Palette
#
# Two numbers generate the whole thing. NEUTRAL_STEPS shades run #000000 to
# #FFFFFF; RED_STEPS shades run from the page's --red mixed toward black
# (shadows), through the token itself, to --red mixed toward white (tints).
# Nothing else is ever emitted, so the only hues present are the neutral axis
# and that single red - a photograph's blues and skin tones cannot survive
# quantisation into it.
#
# RED_HEX is the --red custom property from index-pixel.html's :root.
# ---------------------------------------------------------------------------
RED_HEX = "#a1121b"
NEUTRAL_STEPS = 11      # 8..12
RED_STEPS = 5           # 4..6
RED_MIX = 0.72          # how far the end stops travel toward black / white


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def build_palette(n_neutral: int = NEUTRAL_STEPS, n_red: int = RED_STEPS):
    """Return (neutral_ramp, red_ramp), each dark -> light, as RGB tuples."""
    neutral = []
    for i in range(n_neutral):
        v = int(round(255 * i / (n_neutral - 1)))
        neutral.append((v, v, v))
    base = _hex(RED_HEX)
    red = []
    for i in range(n_red):
        u = (i / (n_red - 1)) * 2 - 1          # -1 (shadow) .. +1 (tint)
        if u < 0:
            red.append(_mix(base, (0, 0, 0), -u * RED_MIX))
        else:
            red.append(_mix(base, (255, 255, 255), u * RED_MIX))
    return neutral, red


# 4x4 Bayer matrix centred on zero. Ordered dithering keeps its texture on a
# regular lattice, so it reads as screen-printing rather than as the static
# error diffusion leaves on a face.
BAYER4 = (np.array([[0, 8, 2, 10],
                    [12, 4, 14, 6],
                    [3, 11, 1, 9],
                    [15, 7, 13, 5]], dtype=np.float32) + 0.5) / 16.0 - 0.5


@dataclass
class Spec:
    slug: str
    file: str
    section: str
    width_class: str          # thumb | half | full
    float_side: str           # left | right | none
    grid: int                 # true pixel-art width, in blocks
    colors: int               # ppa -c, now sized near the final palette
    scale: int                # ppa -s (the intermediate's block size)
    scale_wide: int           # display scale, desktop
    scale_narrow: int         # display scale, phones
    crop: tuple | None = None  # (l, t, r, b) as 0-1 fractions
    contrast: float = 1.0
    bright: float = 0.0
    gamma: float = 1.0
    # Input luma window stretched across the ramp. This is the main lever for
    # re-weighting an image onto a white page: lowering white_point drives the
    # subject down into the dark half of the ramp.
    black_point: float = 0.04
    white_point: float = 0.96
    # Shades available to this image. Fewer reads blockier, more reads smoother.
    neutral_steps: int = NEUTRAL_STEPS
    red_steps: int = RED_STEPS
    # 'none' | 'ordered' | 'fs'. Faces get 'none'; large flat gradients - a
    # sky, a lit wall, a seamless backdrop - get 'ordered'.
    dither: str = "none"
    dither_strength: float = 0.5
    red: bool = False
    # Skin, brick and warm light are all mildly red, so the gates are strict.
    # On white the red reads stronger than it did on the dark page, so less of
    # it goes further and most images are left neutral-only.
    red_sat: float = 0.62
    red_hue: float = 0.34
    red_max_luma: float = 0.42
    note: str = ""


# ---------------------------------------------------------------------------
# Per-image settings - the whole tuning surface lives here.
#   thumb = 54 blocks shown at 216px (4px blocks)
#   half  = 81 blocks shown at 324px (4px blocks)
#   full  = 81 blocks shown at 486px (6px blocks)
# ppa always runs at scale 6; the display scale is separate.
# ---------------------------------------------------------------------------
SPECS: list[Spec] = [
    Spec("finger-stick-blood-drop", "finger-stick-blood-drop.jpg",
         section="Hero", width_class="half", float_side="right",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.36, 0.20, 0.90, 0.74), contrast=1.40,
         black_point=0.16, white_point=0.84,
         dither="ordered", dither_strength=0.60,
         red=True, red_hue=0.40, red_sat=0.70, red_max_luma=0.40,
         note="high-key source. Cropped tighter so the tip fills the frame and "
              "white_point pulled right down, so the finger lands in the mid "
              "greys and its shadowed underside goes dark: on white the "
              "silhouette, not the highlight, has to carry it"),

    Spec("holmes-techcrunch-disrupt-2014", "holmes-techcrunch-disrupt-2014.jpg",
         section="01 Founding", width_class="half", float_side="left",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.165, 0.135, 0.405, 0.52), contrast=1.10,
         black_point=0.06, white_point=0.90,
         dither="none",
         red=False, note="promoted thumb -> half so the face gets 81 blocks"),

    Spec("theranos-nanotainer", "theranos-nanotainer.jpg",
         section="02 Promise", width_class="thumb", float_side="right",
         grid=54, colors=14, scale=6, scale_wide=4, scale_narrow=5,
         crop=(0.175, 0.415, 0.325, 0.80), contrast=1.12,
         black_point=0.05, white_point=0.92,
         dither="none",
         red=True, red_hue=0.16, red_sat=0.38, red_max_luma=0.50,
         note="object, not a face: stays a thumbnail"),

    Spec("fortune-cover-2014", "fortune-cover-2014.png",
         section="03 Funding", width_class="half", float_side="left",
         grid=81, colors=16, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.02, 0.01, 0.99, 0.90), contrast=1.06,
         black_point=0.05, white_point=0.93,
         dither="none",
         red=True, red_hue=0.28, red_sat=0.52, red_max_luma=0.58,
         note="promoted thumb -> half; red = the cover's own red type"),

    Spec("biden-theranos-facility-2015", "biden-theranos-facility-2015.jpg",
         section="05 Prestige", width_class="half", float_side="right",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.14, 0.10, 0.86, 0.92), contrast=1.14,
         black_point=0.05, white_point=0.90,
         dither="ordered", dither_strength=0.40,
         red=False, note="flat walls and a lit banner: ordered dither helps"),

    Spec("walgreens-theranos-check-in", "walgreens-theranos-check-in.jpg",
         section="06 Walgreens", width_class="half", float_side="left",
         grid=81, colors=12, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.19, 0.045, 0.605, 0.30), contrast=1.26, neutral_steps=9,
         black_point=0.10, white_point=0.92,
         dither="none",
         red=True, red_hue=0.22, red_sat=0.46, red_max_luma=0.62,
         note="red gates tightened: at sat 0.30 the warm ceiling above the "
              "signboard was being painted as a red band across the top"),

    Spec("edison-trial-exhibit-5388", "edison-trial-exhibit-5388.jpg",
         section="07 Technology", width_class="full", float_side="none",
         grid=81, colors=14, scale=6, scale_wide=6, scale_narrow=3,
         crop=(0.21, 0.00, 0.79, 0.92), contrast=1.08,
         black_point=0.03, white_point=0.93,
         dither="ordered", dither_strength=0.35,
         red=False, note="object shot; the screen's tiles are multi-hued so no red"),

    Spec("cheung-shultz", "cheung-shultz.jpg",
         section="09 Employees", width_class="half", float_side="right",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.235, 0.04, 0.775, 0.52), contrast=1.10, bright=0.02,
         black_point=0.05, white_point=0.91,
         dither="none",
         red=False, note="promoted thumb -> half: two faces need the width"),

    Spec("carreyrou-bad-blood", "carreyrou-bad-blood.jpg",
         section="10 Scrutiny", width_class="half", float_side="left",
         grid=81, colors=16, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.00, 0.00, 1.00, 1.00), contrast=1.08,
         black_point=0.04, white_point=0.92,
         dither="none",
         red=True, red_hue=0.26, red_sat=0.50, red_max_luma=0.62,
         note="red = the Bad Blood cover type"),

    Spec("theranos-headquarters", "theranos-headquarters.jpg",
         section="11 Ended", width_class="half", float_side="right",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.405, 0.47, 0.695, 0.82), contrast=1.22,
         black_point=0.07, white_point=0.84,
         dither="ordered", dither_strength=0.35,
         red=False,
         note="promoted thumb -> half: at 54 blocks the wordmark on the "
              "monument was mud, and this is the only image where the subject "
              "is lettering rather than a shape"),

    Spec("holmes-federal-courthouse", "holmes-federal-courthouse.jpg",
         section="12 After", width_class="half", float_side="left",
         grid=81, colors=14, scale=6, scale_wide=4, scale_narrow=3,
         crop=(0.38, 0.05, 0.66, 0.70), contrast=1.12, bright=0.08,
         black_point=0.04, white_point=0.88,
         dither="none",
         red=True, red_hue=0.30, red_sat=0.54, red_max_luma=0.52,
         note="re-attempted with the full ramp at 81 blocks; see the report"),
]


# ---------------------------------------------------------------------------
def find_ppa() -> list[str]:
    exe = shutil.which("ppa")
    if exe:
        return [exe]
    base = sysconfig.get_path("scripts", scheme="nt_user") or ""
    cand = Path(base) / "ppa.exe"
    if cand.exists():
        return [str(cand)]
    return [sys.executable, "-m", "ppa"]


PPA = find_ppa()


def stage1_intermediate(spec: Spec, dst: Path) -> tuple[int, int, Image.Image]:
    """Crop, stretch contrast, snap to the block grid, upscale hard.

    Also returns the true-resolution RGB grid. The red mask is taken from this
    rather than from ppa's output: ppa quantises to `-c` colours and a small
    accent (the blood inside the tube, the icon on a sign) is exactly the thing
    a small quantisation throws away.
    """
    im = Image.open(SRC_DIR / spec.file).convert("RGB")
    if spec.crop:
        w, h = im.size
        l, t, r, b = spec.crop
        im = im.crop((round(w * l), round(h * t), round(w * r), round(h * b)))

    gw = spec.grid
    gh = max(1, round(gw * im.size[1] / im.size[0]))

    a = np.asarray(im, dtype=np.float32) / 255.0
    a = (a - 0.5) * spec.contrast + 0.5 + spec.bright
    if spec.gamma != 1.0:
        a = np.clip(a, 0.0, 1.0) ** spec.gamma
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "RGB")

    # area-average down to the grid (nearest would sample single noisy pixels),
    # then nearest-neighbour back up so every block is flat and aligned
    small = im.resize((gw, gh), Image.BOX)
    small.resize((gw * spec.scale, gh * spec.scale), Image.NEAREST).save(dst)
    return gw, gh, small


def stage2_ppa(src: Path, out_dir: Path, spec: Spec, mesh_dir: Path | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = PPA + [str(src), "-o", str(out_dir),
                 "-c", str(spec.colors), "-s", str(spec.scale),
                 "-w", str(spec.scale)]
    if mesh_dir:
        cmd += ["--intermediate-dir", str(mesh_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ppa failed for {spec.slug}:\n{res.stdout}\n{res.stderr}")
    pngs = sorted(out_dir.glob("*.png"))
    if not pngs:
        raise RuntimeError(f"ppa produced nothing for {spec.slug}")
    return pngs[-1]


def to_true_resolution(path: Path, block: int, gw: int, gh: int) -> Image.Image:
    """Reduce ppa's upscaled output back to one pixel per block."""
    im = Image.open(path).convert("RGB")
    if im.size != (gw * block, gh * block):
        im = im.resize((gw * block, gh * block), Image.NEAREST)
    return im.resize((gw, gh), Image.NEAREST)


def _floyd_steinberg(v: np.ndarray, n: int, strength: float) -> np.ndarray:
    """Return luma pre-biased so that plain rounding reproduces damped FS."""
    work = v.copy()
    h, w = work.shape
    for y in range(h):
        for x in range(w):
            old = work[y, x]
            q = np.clip(round(float(np.clip(old, 0.0, 1.0)) * (n - 1)), 0, n - 1) / (n - 1)
            err = (old - q) * strength
            if x + 1 < w:
                work[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += err * 3 / 16
                work[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    work[y + 1, x + 1] += err * 1 / 16
    return work


def palette_lock(true_res: Image.Image, chroma_src: Image.Image, spec: Spec) -> Image.Image:
    """Quantise luma onto the generated ramps.

    Tone comes from ppa's grid-snapped output; the red mask comes from
    chroma_src, the pre-quantisation grid. Masked pixels are quantised onto
    the red ramp and everything else onto the neutral ramp, so a desaturated
    area can never drift onto a pale red tint and no third hue can appear.
    """
    neutral, red = build_palette(spec.neutral_steps, spec.red_steps)
    a = np.asarray(true_res, dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b

    lo, hi = spec.black_point, spec.white_point
    luma = np.clip((luma - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    red_mask = np.zeros(luma.shape, dtype=bool)
    if spec.red:
        c = np.asarray(chroma_src, dtype=np.float32) / 255.0
        cr, cg, cb = c[..., 0], c[..., 1], c[..., 2]
        c_luma = 0.299 * cr + 0.587 * cg + 0.114 * cb
        mx = c.max(axis=-1)
        mn = c.min(axis=-1)
        sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
        redness = cr - np.maximum(cg, cb)
        red_mask = (sat >= spec.red_sat) & (redness >= spec.red_hue) & (c_luma <= spec.red_max_luma)

    h, w = luma.shape
    out = np.empty((h, w, 3), dtype=np.uint8)

    for mask, ramp in ((~red_mask, neutral), (red_mask, red)):
        if not mask.any():
            continue
        n = len(ramp)
        v = luma.copy()
        if spec.dither == "ordered":
            tile = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
            v = v + tile * (spec.dither_strength / (n - 1))
        elif spec.dither == "fs":
            v = _floyd_steinberg(v, n, spec.dither_strength)
        idx = np.clip(np.rint(np.clip(v, 0.0, 1.0) * (n - 1)), 0, n - 1).astype(np.int32)
        for k, col in enumerate(ramp):
            sel = mask & (idx == k)
            if sel.any():
                out[sel] = col
    return Image.fromarray(out, "RGB")


def save_scaled(img: Image.Image, scale: int, dst: Path) -> tuple[int, int]:
    w, h = img.size
    big = img.resize((w * scale, h * scale), Image.NEAREST)
    # 32 slots is comfortably above the 12-18 the ramps can emit, so the
    # indexed conversion is lossless rather than a second quantisation
    big = big.convert("P", palette=Image.ADAPTIVE, colors=32)
    big.save(dst, optimize=True)
    return w * scale, h * scale


def unique_colors(path: Path) -> list[str]:
    arr = np.asarray(Image.open(path).convert("RGB")).reshape(-1, 3)
    return ["#%02x%02x%02x" % tuple(int(c) for c in row)
            for row in np.unique(arr, axis=0)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--keep-intermediate", action="store_true")
    args = ap.parse_args()

    neutral, red = build_palette()
    print("ppa:", " ".join(PPA))
    print(f"palette: {len(neutral)} neutral + {len(red)} red = {len(neutral) + len(red)}")
    print("  neutral:", " ".join("#%02x%02x%02x" % c for c in neutral))
    print("  red    :", " ".join("#%02x%02x%02x" % c for c in red))
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    done = 0
    try:
        for spec in SPECS:
            if args.only and spec.slug != args.only:
                continue
            src = SRC_DIR / spec.file
            if not src.exists():
                print(f"  !! missing source {spec.file}", file=sys.stderr)
                continue

            inter = WORK_DIR / f"{spec.slug}-intermediate.png"
            gw, gh, chroma = stage1_intermediate(spec, inter)

            ppa_dir = WORK_DIR / spec.slug
            mesh = (WORK_DIR / f"{spec.slug}-mesh") if args.keep_intermediate else None
            produced = stage2_ppa(inter, ppa_dir, spec, mesh)

            true_res = to_true_resolution(produced, spec.scale, gw, gh)
            locked = palette_lock(true_res, chroma, spec)

            sizes = {}
            for variant, sc in (("wide", spec.scale_wide), ("narrow", spec.scale_narrow)):
                dst = OUT_DIR / f"{spec.slug}-{variant}.png"
                sizes[variant] = save_scaled(locked, sc, dst)

            wide = OUT_DIR / f"{spec.slug}-wide.png"
            ncol = len(unique_colors(wide))
            print(f"  {spec.slug:<32} {spec.width_class:<5} grid {gw:>3}x{gh:<3} "
                  f"wide {sizes['wide'][0]}x{sizes['wide'][1]}  "
                  f"narrow {sizes['narrow'][0]}x{sizes['narrow'][1]}  "
                  f"-c {spec.colors:<2} {spec.dither:<7} "
                  f"colors {ncol:<2} {wide.stat().st_size/1024:5.1f} KB "
                  f"{'RED' if spec.red else '---'}")
            done += 1
    finally:
        if not args.keep_intermediate and WORK_DIR.exists():
            shutil.rmtree(WORK_DIR, ignore_errors=True)

    pngs = sorted(OUT_DIR.glob("*.png"))
    total = sum(p.stat().st_size for p in pngs)
    over = [p.name for p in pngs if p.stat().st_size > 200 * 1024]
    print(f"\n{done} image(s), {len(pngs)} files, {total/1024:.0f} KB total in {OUT_DIR}")
    if over:
        print("OVER 200 KB:", ", ".join(over))

    with (OUT_DIR / "_colors.txt").open("w", encoding="utf-8") as f:
        for p in pngs:
            cs = unique_colors(p)
            f.write(f"{p.name}\t{len(cs)}\t{' '.join(sorted(cs))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
