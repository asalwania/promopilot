"""Cut the deck's screenshot crops from the 1920x1080 captures in frontend/screenshots/.

Run from the repo root:  uv run --no-project --with pillow python docs/deck/crops.py
Input:  frontend/screenshots/NN-*.png  (from `make screenshots` or CI's `deck-screenshots` artifact)
Output: frontend/screenshots/deck/<name>.png, one per CROPS entry (gitignored, like the captures).

Each crop is a (left, top, right, bottom) pixel box on the 1920x1080 capture. The boxes frame one
panel each so the text stays legible once the slide scales the image down.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "screenshots"
OUT = SRC / "deck"

# Crops that end at the capture's bottom edge get this many pixels of white added below them,
# so the card's frame closes instead of being cut by the screen edge.
PAD_BOTTOM: dict[str, int] = {"audit-trail": 16}

# name: (source capture, (left, top, right, bottom))
CROPS: dict[str, tuple[str, tuple[int, int, int, int]]] = {
    "home-hero": ("01-home-example-briefs.png", (395, 100, 1515, 1080)),
    "trace-clean": ("05-plan-region-tabs.png", (225, 85, 605, 795)),
    "trace-loop": ("13-simulation-band-chart.png", (225, 150, 605, 950)),
    "clarify": ("02-clarification-form.png", (630, 85, 1695, 315)),
    "assumptions": ("03-assumptions-panel.png", (630, 85, 1695, 560)),
    "assumptions-inferred": ("03-assumptions-panel.png", (630, 660, 1695, 960)),
    "diff-budget": ("15-amend-diff-budget-cut.png", (650, 90, 1675, 400)),
    "diff-drop-west": ("16-amend-diff-drop-west.png", (650, 90, 1675, 350)),
    "audit-trail": ("18-approved-audit-trail.png", (630, 940, 1695, 1080)),
    "approve": ("17-approve-confirm.png", (630, 85, 1695, 405)),
    "reject": ("19-reject-plan.png", (630, 85, 1695, 465)),
    "infeasible": ("20-infeasibility-panel.png", (650, 90, 1675, 625)),
    "mechanisms": ("07-mechanism-drawer.png", (1152, 0, 1920, 320)),
    "uplift-segments": ("11-cannibalisation-halo-callouts.png", (650, 85, 1130, 320)),
    "callouts": ("11-cannibalisation-halo-callouts.png", (1265, 85, 1695, 235)),
    "plan-table": ("05-plan-region-tabs.png", (650, 88, 1695, 530)),
    "compare-regions": ("06-compare-regions.png", (650, 88, 1675, 500)),
    "competitor": ("12-competitor-panel.png", (650, 95, 1675, 560)),
    "simulation": ("13-simulation-band-chart.png", (650, 215, 1675, 870)),
    "simulation-tiles": ("13-simulation-band-chart.png", (650, 215, 1675, 510)),
    "stress-test": ("14-simulation-stress-test.png", (650, 215, 1675, 510)),
    "constraints": ("09-constraint-checklist.png", (650, 95, 1675, 440)),
    "not-selected": ("09-constraint-checklist.png", (650, 480, 1675, 925)),
    "evals-plan-quality": ("21-evals-dashboard.png", (415, 790, 1505, 1050)),
    "evals-top": ("21-evals-dashboard.png", (415, 300, 1505, 760)),
    "llm-usage": ("17-approve-confirm.png", (630, 425, 1695, 535)),
}


def main() -> int:
    missing = [src for src, _ in CROPS.values() if not (SRC / src).exists()]
    if missing:
        print("missing captures:", ", ".join(sorted(set(missing))), file=sys.stderr)
        print(
            "run `make screenshots` or unzip CI's deck-screenshots artifact first", file=sys.stderr
        )
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (src, box) in CROPS.items():
        with Image.open(SRC / src) as img:
            if img.size != (1920, 1080):
                print(
                    f"{src}: expected 1920x1080, got {img.size[0]}x{img.size[1]}", file=sys.stderr
                )
                return 1
            crop = img.crop(box)
            if pad := PAD_BOTTOM.get(name):
                padded = Image.new("RGB", (crop.width, crop.height + pad), "#ffffff")
                padded.paste(crop, (0, 0))
                crop = padded
            crop.save(OUT / f"{name}.png", optimize=True)
            print(f"{name}.png  {crop.size[0]}x{crop.size[1]}  from {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
