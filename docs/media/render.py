"""Render the local README media; --assists-only leaves approved battery files alone.

Documentation tooling only. Requires rsvg-convert and ImageMagick (`magick`).
Run from the repo root: python docs/media/render.py
"""
import argparse
from html import escape
from pathlib import Path
import subprocess
import tempfile

from field_guide import OVERVIEW_NAME, SCENES, render as render_field_guide

MEDIA = Path(__file__).resolve().parent


def raster(source, target):
    subprocess.run(["rsvg-convert", str(source), "-o", str(target)], check=True)


def render_assists():
    render_field_guide(MEDIA)
    # Palette PNGs keep these textured illustrations under a few hundred KB each.
    with tempfile.TemporaryDirectory(prefix="cria-field-guide-") as scratch:
        for name in [s[0] for s in SCENES] + [OVERVIEW_NAME]:
            source = MEDIA / f"{name}.svg"
            raw = Path(scratch) / f"{name}.png"
            raster(source, raw)
            subprocess.run(["magick", str(raw), "-strip", "-dither", "None", "-colors", "256",
                            "-define", "png:compression-level=9", f"PNG8:{MEDIA / (name + '.png')}"],
                           check=True)


def render_replay():
    record = (MEDIA / "tool-repair-run.txt").read_text().splitlines()
    command = record[0].removeprefix("Command: ")
    lines = record[record.index("FIXED-INPUT REPLAY / no model calls / no shell execution"):]
    # Reveal the actual transcript by section, not by manufactured execution timing.
    ends = [2, lines.index("OUTPUT / a structured call the harness can receive"),
            lines.index("CHECK / tool name and arguments preserved; integer type verified"), len(lines)]
    with tempfile.TemporaryDirectory(prefix="cria-readme-media-") as scratch:
        args = ["magick"]
        for number, end in enumerate(ends):
            visible = []
            for i, value in enumerate(lines[:end]):
                color = "#76ceda" if value.startswith(("INPUT /", "OUTPUT /")) else "#d4e4eb"
                if value.startswith(("CHECK /", "BOUNDARY /")):
                    color = "#ffd264"
                visible.append(f'<text x="64" y="{229 + i * 34}" fill="{color}" '
                               f'xml:space="preserve">{escape(value)}</text>')
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1060" viewBox="0 0 1600 1060">
<rect width="1600" height="1060" rx="24" fill="#0b1b29"/>
<path d="M40 115H1560" stroke="#335469"/>
<g font-family="DejaVu Sans, sans-serif">
<text x="64" y="58" fill="#f0f7fa" font-size="32" font-weight="700">Tool-call repair</text>
<text x="64" y="94" fill="#91adbd" font-size="22">Code replay</text>
</g>
<g font-family="DejaVu Sans Mono, monospace" font-size="24">
<text x="64" y="170" fill="#76ceda">$ {escape(command)}</text>
{''.join(visible)}
</g>
<path d="M40 986H1560" stroke="#335469"/>
</svg>'''
            source = Path(scratch) / f"frame-{number}.svg"
            target = source.with_suffix(".png")
            source.write_text(svg)
            raster(source, target)
            args.extend(["-delay", str([120, 350, 400, 850][number]), str(target)])
        args.extend(["-loop", "0", "-layers", "Optimize", str(MEDIA / "tool-repair.gif")])
        subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--assists-only", action="store_true",
                       help="Render only the field-guide scenes, without touching battery/hero/replay files")
    scope.add_argument("--battery-only", action="store_true",
                       help="Render only the stored battery grids and comparison tables")
    args = parser.parse_args()
    if not args.battery_only:
        render_assists()
    if args.assists_only:
        return
    from battery_media import render as render_battery
    render_battery()
    for name in ("battery-l0", "battery-l5"):
        raster(MEDIA / f"{name}.svg", MEDIA / f"{name}.png")
    if args.battery_only:
        return
    # The README uses the vector architecture diagram; its raster remains a review copy.
    for name in ("hero", "execution-boundary"):
        raster(MEDIA / f"{name}.svg", MEDIA / f"{name}.png")
    render_replay()
    print("Rendered README artwork, field-guide illustrations, frozen battery grids, and replay.")


if __name__ == "__main__":
    main()
