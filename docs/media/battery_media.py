"""Render the frozen battery display data as heatmaps and readable tables."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path

MEDIA = Path(__file__).resolve().parent
BG = "#0b1b29"
PANEL = "#122c3d"
INK = "#f0f7fa"
MUTED = "#a6c1cf"
CYAN = "#76ceda"
GOLD = "#ffd264"


def text(x, y, value, size=27, color=INK, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')


def rect(x, y, w, h, fill=PANEL, stroke="#335469", radius=14):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}"/>')


def svg(title, desc, body, height):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" viewBox="0 0 1600 {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc>
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="{CYAN}"/></marker></defs>
<rect width="1600" height="{height}" rx="24" fill="{BG}"/>
<g font-family="DejaVu Sans, sans-serif">{body}</g></svg>'''


def mean(values):
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def overall(level):
    return mean([v for row in level["rows"] for v in row["cells"]])


def common_labels(data):
    """Same displayed labels only; revisions/variants are not experimental pairs."""
    a = {r["model"]: r["cells"] for r in data["levels"]["0"]["rows"]}
    b = {r["model"]: r["cells"] for r in data["levels"]["5"]["rows"]}
    pairs = [(x, y) for model in a.keys() & b.keys() for x, y in zip(a[model], b[model])
             if x is not None and y is not None]
    return len(pairs), mean([p[0] for p in pairs]), mean([p[1] for p in pairs])


def heat_color(value):
    if value is None:
        return "#122535", "#8ba8b9"
    if value >= 87.5:
        return "#163e36", "#8de0b2"
    if value >= 62.5:
        return "#403c22", "#ffe080"
    if value >= 37.5:
        return "#452d22", "#ffb57f"
    return "#402836", "#ffa3ab"


def heatmaps(data):
    for level, title in [("0", "L0 · Wire translation"), ("5", "L5 · Full engagement")]:
        scores = data["levels"][level]
        best = scores.get("selection") == "best-recorded"
        rows = {row["model"]: row["cells"] for row in scores["rows"]}
        body = (text(64, 63, "TASK BATTERY / INFERRED USEFULNESS", 24, CYAN, 700)
                + text(64, 132, title, 52, INK, 700)
                + text(1536, 122, f'{scores["overall"]}%', 70, CYAN, 700, "end")
                + text(1536, 168, "overall average", 24, MUTED, anchor="end")
                + text(64, 223, "MODEL / PROJECT IDENTITY", 22, MUTED, 700))
        xcols = [438 + 130 * i for i in range(6)]
        for x, label in zip(xcols, data["task_labels"]):
            body += text(x + 58, 223, label, 25, MUTED, 700, "middle")
        body += text(1435, 223, "ROW AVG", 22, MUTED, 700, "middle")
        for i, model in enumerate(data["model_order"]):
            y = 247 + i * 73
            body += rect(48, y, 1504, 65, "#102332" if i % 2 == 0 else BG, BG, 8)
            body += text(70, y + 42, model, 27, INK, 700)
            cells = rows.get(model, [None] * 6)
            for x, value in zip(xcols, cells):
                fill, ink = heat_color(value)
                body += rect(x, y + 3, 116, 59, fill, fill, 10)
                body += text(x + 58, y + 42, "—" if value is None else f"{value}%", 29, ink, 700, "middle")
            avg = mean(cells)
            body += text(1435, y + 42, "—" if avg is None else f"{round(avg)}%", 29, INK, 700, "middle")
        y = 247 + len(data["model_order"]) * 73 + 34
        body += text(64, y, f"OVERALL / {overall(scores):.1f}%", 27, CYAN, 700)
        for i, (label, value) in enumerate([("≥88", 88), ("≥63", 63), ("≥38", 38), ("<38", 0)]):
            fill, ink = heat_color(value)
            body += rect(64 + 160 * i, y + 35, 138, 44, fill, fill, 8)
            body += text(133 + 160 * i, y + 66, label, 24, ink, 700, "middle")
        body += text(760, y + 66, "— = not judged", 24, MUTED)
        title_text = f"{title}, average {scores['overall']} percent"
        desc = ("Inferred usefulness; L5 cells select historical maxima, documented in the README. " if best else
                "Inferred usefulness from the standing snapshot. ") + "; ".join(
            f"{m}: " + ", ".join(f"{label} " + ("not judged" if v is None else f"{v} percent")
            for label, v in zip(data["task_labels"], rows.get(m, [None] * 6))) for m in data["model_order"])
        (MEDIA / f"battery-l{level}.svg").write_text(svg(title_text, desc, body, y + 113))


def comparison_text(data):
    out = ["# L0 standing / L5 best recorded", "",
           "**Metric: holistically inferred usefulness, not deterministic task scores or pass rates.**", "",
           "L0 retains the standing snapshot. L5 selects the highest retained final judgment per "
           "model/task, including historical runs and frozen inference summaries. It is not one "
           "campaign, expected performance, a new run or a fresh re-audit of every capture.", "",
           "Phi-4 is temporarily omitted from the displayed roster; its original data is retained. "
           "Averages reflect the displayed roster, not a new run. Ornith L0 remains unknown: "
           "[retained-history search and unsupported draft row](ornith-l0-search.md).", ""]
    for level in ("0", "5"):
        scores = data["levels"][level]
        values = [v for row in scores["rows"] for v in row["cells"] if v is not None]
        selection = "mean of cell maxima" if scores.get("selection") == "best-recorded" else "standing overall average"
        out += [f"## L{level} — {scores['overall']}% {selection} ({overall(scores):.1f}% before rounding)", "",
                f"{len(values)} judged cells. Equal weight per observed cell, not per model. "
                "Missing cells excluded; observed zeros included.", "",
                "| Model | " + " | ".join(data["task_labels"]) + " | Row average |",
                "|---|" + "---:|" * 7]
        rows = {r["model"]: r["cells"] for r in scores["rows"]}
        for model in data["model_order"]:
            cells = rows.get(model, [None] * 6)
            avg = mean(cells)
            out.append("| " + model + " | " + " | ".join("—" if v is None else f"{v}%" for v in cells)
                       + " | " + ("—" if avg is None else f"{round(avg)}%") + " |")
        out.append("")
    count, a, b = common_labels(data)
    out += ["## Reading the comparison", "",
            f"Restricting both grids to the same available model/task **labels** gives {count} cells: "
            f"L0 standing **{a:.1f}%**, L5 selected maxima **{b:.1f}%**. "
            "These are **not controlled experimental pairs**: only L5 is maximized across history.", "",
            "Selecting historical maxima is intentionally optimistic and does not establish typical "
            "performance or a causal improvement. Investigate missing, mistimed or incorrect cria assists; "
            "do not turn low usefulness into a verdict on model weights.", "",
            "Rosters, run dates, source revisions, model variants and planner settings differ. "
            "The historical L5 label included planner experiments; planning is currently off by default. "
            "Gemma4/QAT share one official identity: unreplaced cells keep frozen stock-model history. "
            "Do not read the resulting row as one unchanged model configuration. Defiant-Fable "
            "is merged into qwen3.8_9b_distill per the owner's identity correction; original IDs are preserved.", "",
            "Some recent full captures are unavailable in the source checkout. Reported values are preserved, "
            "not independently re-judged here. A new controlled, planner-off campaign is needed before "
            "claiming an assist uplift.", "",
            "## Sources", "",
            f"Reporting snapshot: **{data['provenance']['report_date']} "
            f"{data['provenance']['report_timezone']}**. This is the report's export timestamp, "
            "not the date of every underlying run.", "",
            f"L5 best-recorded export: **{data['levels']['5']['provenance']['report_date']} "
            f"{data['levels']['5']['provenance']['report_timezone']}**.", "",
            "[L5 cell-by-cell sources and retained-history scope](battery-l5-best.json) · "
            "[Original standing reporting output](battery-report-snapshot.md) · "
            "[Display data and source checksums](battery-data.json) · "
            "[Capture/reproduction notes](README.md#battery-snapshot)", ""]
    (MEDIA / "battery-comparison.md").write_text("\n".join(out))


def render():
    data = json.loads((MEDIA / "battery-data.json").read_text())
    heatmaps(data)
    comparison_text(data)
    print("Rendered frozen battery SVGs and accessible comparison tables.")


if __name__ == "__main__":
    render()
