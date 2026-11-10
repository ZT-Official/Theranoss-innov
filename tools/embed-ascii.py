#!/usr/bin/env python3
"""
embed-ascii.py - fill the ASCII placeholders in index-ascii.html.

The page carries one marker pair per picture variant:

    <pre class="ascii-art wide for-light" style="--cols:118" aria-hidden="true"
      ><!--A:finger-stick-blood-drop-wide--><!--/A--></pre>

Everything between <!--A:NAME--> and <!--/A--> is replaced with the escaped
contents of assets/ascii/NAME.txt. The markers stay in place, so the script is
idempotent: run asciify.ps1, run this, and the page is current.

For the two pictures that are literally blood, the densest glyphs are wrapped
in <b> so they take the page's red. That is only done for the light-theme
files: the dark-theme files are tone-reversed, so there the dark part of the
photograph is the ABSENCE of glyphs and there is nothing to colour.

Usage:  python tools/embed-ascii.py [--check]
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "index-ascii.html"
ASCII_DIR = ROOT / "assets" / "ascii"

# Dense end of ascii-image-converter's built-in extended ramp. In a light-theme
# file these glyphs sit on the darkest pixels of the photograph.
HOT = {
    "finger-stick-blood-drop": "$@B%",   # extended ramp, darkest four
    "theranos-nanotainer": "@",          # RampFace, darkest only: the blood column
}

MARKER = re.compile(r"(<!--A:([A-Za-z0-9\-]+)-->)(.*?)(<!--/A-->)", re.S)

ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def render(text: str, hot: str) -> str:
    """HTML-escape, wrapping runs of `hot` characters in <b>."""
    out = []
    in_b = False
    for ch in text:
        is_hot = bool(hot) and ch in hot
        if is_hot and not in_b:
            out.append("<b>")
            in_b = True
        elif not is_hot and in_b:
            out.append("</b>")
            in_b = False
        out.append(ESCAPE.get(ch, ch))
    if in_b:
        out.append("</b>")
    return "".join(out)


def main() -> int:
    check_only = "--check" in sys.argv
    if not PAGE.exists():
        print(f"missing page: {PAGE}", file=sys.stderr)
        return 1

    html = PAGE.read_text(encoding="utf-8")
    seen, missing, stats = [], [], []

    def sub(m):
        open_tag, name, _old, close_tag = m.groups()
        src = ASCII_DIR / f"{name}.txt"
        if not src.exists():
            missing.append(name)
            return m.group(0)
        body = src.read_text(encoding="utf-8").rstrip("\n")
        slug = name.rsplit("-wide", 1)[0].rsplit("-narrow", 1)[0]
        hot = HOT.get(slug, "") if not name.endswith("-dark") else ""
        rendered = render(body, hot)
        seen.append(name)
        rows = body.count("\n") + 1
        cols = max((len(l) for l in body.split("\n")), default=0)
        stats.append((name, cols, rows, len(rendered)))
        return open_tag + rendered + close_tag

    new_html = MARKER.sub(sub, html)

    if missing:
        print("MISSING .txt for: " + ", ".join(missing), file=sys.stderr)
        return 1
    if not seen:
        print("no <!--A:...--> markers found", file=sys.stderr)
        return 1

    for name, cols, rows, size in sorted(stats):
        print(f"  {name:<46} {cols:>4} x {rows:<3} {size:>7,} B")

    if check_only:
        print(f"\n{len(seen)} block(s); page would be {len(new_html):,} bytes")
        return 0 if new_html == html else 2

    PAGE.write_text(new_html, encoding="utf-8", newline="\n")
    print(f"\n{len(seen)} block(s) embedded; {PAGE.name} is {len(new_html):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
