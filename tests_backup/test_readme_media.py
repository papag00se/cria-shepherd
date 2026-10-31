"""Documentation rendering: preserve reported scores, zeros, missing cells and averaging."""
import importlib.util
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from suite import battery_status

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs/media"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), MEDIA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot = load("snapshot-battery")
battery_media = load("battery_media")
field_guide = load("field_guide")
best_l5 = load("best_l5")


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(battery_status, "_historical", lambda: {
        "task_labels": ["ruby", "go", "python", "java", "node", "rust"],
    })
    # Synthetic report fixture, not measurements of a model.
    rows = [
        {"model": "bonsai2", "task": "shipping-rates-rb", "level": 0, "usefulness_percent": 100},
        {"model": "bonsai2", "task": "cart-billing-go", "level": 0, "usefulness_percent": 0},
        {"model": "bonsai2", "task": "shipping-rates-rb", "level": 1, "usefulness_percent": 90},
        {"model": "bonsai2", "task": "shipping-rates-rb", "level": 5, "usefulness_percent": 20},
        {"model": "bonsai2", "task": "cart-billing-go", "level": 5, "usefulness_percent": 0},
    ]
    return battery_status.report(rows, now=0)


def test_report_adapter_keeps_levels_distinct_and_missing_cells_unknown(report):
    data = snapshot.parse_report(report)
    assert data["levels"]["0"]["rows"] == [{"model": "bonsai2", "cells": [100, 0, None, None, None, None]}]
    assert data["levels"]["5"]["rows"] == [{"model": "bonsai2", "cells": [20, 0, None, None, None, None]}]
    assert data["levels"]["0"]["overall"] == 50
    assert data["levels"]["5"]["overall"] == 10


def test_report_adapter_rejects_summary_drift(report):
    with pytest.raises(ValueError, match="overall average disagrees"):
        snapshot.parse_report(report.replace("— 50%", "— 51%"))


def test_report_adapter_rejects_reordered_columns(report):
    with pytest.raises(ValueError, match="Unexpected report columns"):
        snapshot.parse_report(report.replace("| ruby | go |", "| go | ruby |"))


def test_averages_include_zero_exclude_missing_and_weight_cells_not_rows():
    assert battery_media.mean([0, None]) == 0
    assert battery_media.mean([None]) is None
    assert battery_media.mean([100, 0, None]) == 50
    level = {"rows": [{"model": "a", "cells": [100] * 6},
                      {"model": "b", "cells": [0, None, None, None, None, None]}]}
    assert battery_media.overall(level) == pytest.approx(600 / 7)


def test_common_labels_exclude_unmatched_cells_without_dropping_zero():
    data = {"levels": {
        "0": {"rows": [{"model": "a", "cells": [0, 100, 50, None, None, None]},
                        {"model": "l0-only", "cells": [100] * 6}]},
        "5": {"rows": [{"model": "l5-only", "cells": [100] * 6},
                        {"model": "a", "cells": [20, 80, None, 100, None, None]}]},
    }}
    assert battery_media.common_labels(data) == (2, 50, 50)


def test_frozen_display_data_agrees_with_authoritative_report():
    data = json.loads((MEDIA / "battery-data.json").read_text())
    parsed = snapshot.parse_report((MEDIA / "battery-report-snapshot.md").read_text())
    assert data["standing_l0"] == parsed["levels"]["0"]
    visible_l0 = [r for r in parsed["levels"]["0"]["rows"] if r["model"] in data["model_order"]]
    assert data["levels"]["0"]["rows"] == visible_l0
    assert data["standing_l5"] == parsed["levels"]["5"]
    best = json.loads((MEDIA / "battery-l5-best.json").read_text())
    for key in ("selection", "overall", "rows", "provenance"):
        assert data["levels"]["5"][key] == best[key]
    selected = {(c["model"], c["task"]): c["score"] for c in best["cells"]}
    for row in best["rows"]:
        assert row["cells"] == [selected.get((row["model"], task)) for task in best_l5.TASKS]
    assert "defiant-fable" not in data["model_order"]
    assert "phi4" not in data["model_order"]
    assert "phi4" in data["roster_model_order"]
    assert "phi4" in data["excluded_models"]
    assert data["task_labels"] == parsed["task_labels"]
    for level in data["levels"].values():
        assert round(battery_media.overall(level)) == level["overall"]
    assert {row["model"] for level in data["levels"].values() for row in level["rows"]} <= set(data["model_order"])


def test_readme_images_are_present_in_this_repository():
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", (ROOT / "README.md").read_text())
    assert images
    for destination in images:
        path = (ROOT / destination).resolve()
        assert path.is_relative_to(ROOT), "README assets must not depend on a separate worktree"
        assert path.is_file(), f"Missing README image: {destination}"
        if path.suffix == ".svg":
            assert ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg"
        elif path.suffix == ".png":
            assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        elif path.suffix == ".gif":
            assert path.read_bytes()[:6] in (b"GIF87a", b"GIF89a")


def test_generate_and_rasterize_charts(tmp_path, monkeypatch):
    shutil.copy(MEDIA / "battery-data.json", tmp_path)
    monkeypatch.setattr(battery_media, "MEDIA", tmp_path)
    battery_media.render()
    for name in ("battery-l0", "battery-l5"):
        source = tmp_path / f"{name}.svg"
        tree = ET.parse(source).getroot()
        assert tree.find("{http://www.w3.org/2000/svg}title").text
        assert tree.find("{http://www.w3.org/2000/svg}desc").text
        labels = [node.text or "" for node in tree.iter("{http://www.w3.org/2000/svg}text")]
        assert ("L0 · Wire translation" if name == "battery-l0" else "L5 · Full engagement") in labels
        assert "overall average" in labels
        assert "— = not judged" in labels
        for phrase in ("Best recorded", "temporarily omitted", "Highest retained", "Selected maxima",
                       "typical performance", "Mixed revisions", "before whole-percent rounding", "REPORT /"):
            assert not any(phrase.lower() in label.lower() for label in labels)
        raster = shutil.which("rsvg-convert")
        if raster:
            target = source.with_suffix(".png")
            subprocess.run([raster, str(source), "-o", str(target)], check=True)
            png = target.read_bytes()
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", png[16:24]) == (int(tree.attrib["width"]), int(tree.attrib["height"]))


def test_field_guide_is_standalone_and_reproducible(tmp_path):
    field_guide.render(tmp_path)
    first = {p.name: p.read_bytes() for p in tmp_path.glob("*.svg")}
    field_guide.render(tmp_path)
    assert first == {p.name: p.read_bytes() for p in tmp_path.glob("*.svg")}
    for name in [s[0] for s in field_guide.SCENES] + [field_guide.OVERVIEW_NAME]:
        root = ET.parse(tmp_path / f"{name}.svg").getroot()
        assert root.find("{http://www.w3.org/2000/svg}title").text
        assert root.find("{http://www.w3.org/2000/svg}desc").text
        labels = [node.text or "" for node in root.iter("{http://www.w3.org/2000/svg}text")]
        assert not any("NOT A CAPTURE" in label for label in labels)
        ids = {element.attrib["id"] for element in root.iter() if "id" in element.attrib}
        for element in root.iter():
            for key, value in element.attrib.items():
                if key.endswith("href"):
                    assert value.startswith("#"), "GitHub illustrations must not require external assets"
                if value.startswith("url(#"):
                    assert value[5:-1] in ids, "Broken local SVG paint/clip/filter reference"


def test_assist_overview_contains_four_distinct_scenes_in_two_rows_and_columns(tmp_path):
    field_guide.render(tmp_path)
    root = ET.parse(tmp_path / f"{field_guide.OVERVIEW_NAME}.svg").getroot()
    ns = "{http://www.w3.org/2000/svg}"
    cells = [node for node in root.iter(ns + "svg") if node is not root]
    assert len(cells) == 4
    xs, ys = {float(c.attrib["x"]) for c in cells}, {float(c.attrib["y"]) for c in cells}
    assert len(xs) == len(ys) == 2
    assert {(float(c.attrib["x"]), float(c.attrib["y"])) for c in cells} == {(x, y) for x in xs for y in ys}
    assert len({ET.tostring(c.find(ns + "g")) for c in cells}) == 4
    for cell in cells:
        assert float(cell.attrib["x"]) + float(cell.attrib["width"]) <= float(root.attrib["width"])
        assert float(cell.attrib["y"]) + float(cell.attrib["height"]) <= float(root.attrib["height"])
    labels = [n.text for n in root.iter(ns + "text")]
    assert labels == [s[2] for s in field_guide.SCENES]


@pytest.mark.skipif(not shutil.which("rsvg-convert") or not shutil.which("magick"),
                    reason="Documentation raster tools are not installed")
def test_assists_only_cli_renders_scenes_without_touching_battery(tmp_path):
    for name in ("render.py", "field_guide.py"):
        shutil.copy(MEDIA / name, tmp_path)
    approved = {name: (MEDIA / name).read_bytes() for name in (
        "battery-l0.svg", "battery-l0.png", "battery-l5.svg", "battery-l5.png",
        "battery-data.json", "battery-report-snapshot.md", "battery-comparison.md")}
    for name, content in approved.items():
        (tmp_path / name).write_bytes(content)
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    subprocess.run([sys.executable, str(tmp_path / "render.py"), "--assists-only"],
                   cwd=other_cwd, check=True, capture_output=True, text=True)
    assert approved == {name: (tmp_path / name).read_bytes() for name in approved}
    for name, *_ in field_guide.SCENES:
        png = (tmp_path / f"{name}.png").read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (1600, 840)
        assert len(png) < 500_000, "Illustrated README assets should remain lightweight"
    overview = (tmp_path / f"{field_guide.OVERVIEW_NAME}.png").read_bytes()
    assert overview[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", overview[16:24]) == (1600, field_guide.OVERVIEW_HEIGHT)
