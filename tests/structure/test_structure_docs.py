"""Generated inventory agrees with the registry; walk process docs and walk output stay consistent."""
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

from suite import walk

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

def test_generated_assist_inventory_agrees_with_the_registry(monkeypatch, capsys):
    """`build_report.py --check`: families cover frozen history, every registered definition is owned/ordered/scoped, and
    REPORT.md + LEVELS.md are exactly what the registry renders (a stale generated doc exits 1)."""
    spec = importlib.util.spec_from_file_location("report", DOCS / "assist-inventory/build_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    monkeypatch.setattr(sys, "argv", ["build_report.py", "--check"])
    assert report.main() == 0, capsys.readouterr().err

def call(tmp_path, number, phase, prompt):
    stem = tmp_path / f"{number:04d}-{phase}"
    Path(f"{stem}.prompt.txt").write_bytes(prompt.encode("utf-8"))
    return f"{number:04d}", phase, stem

def test_walk_sections_reintroduce_context_and_line_references_keep_exact_bytes(tmp_path):
    """Every omitted prompt line is reconstructible from the reader's OWN section (baseline in full, later blocks reference it,
    budget holds); middle changes, deletions, moved/restored lines and CRLF/UTF-8 bytes survive."""
    baseline = "shared context\n" * 200
    calls = [call(tmp_path, i, "coder", baseline + f"new {i}\n") for i in range(1, 5)]
    full = len(walk.emit_call(*calls[0], {}, True).encode("utf-8"))
    sections = walk.render_sections(calls, full + 700, False)
    assert len(sections) > 1 and any(len(s) > 1 for s in sections)
    for section in sections:
        assert baseline in section[0] and "PROMPT COPY" not in section[0]
        assert all(baseline not in b and "PROMPT COPY" in b for b in section[1:])
        assert sum(len(b.encode("utf-8")) for b in section) <= full + 700
    state = {}
    walk.emit_call(*call(tmp_path, 11, "x", "α\r\nold\r\nkept\r\nremove\r\n"), state, False)
    after = walk.emit_call(*call(tmp_path, 12, "x", "α\r\nnew\r\nkept\r\n"), state, False)
    assert "new\r\n" in after and "old\r\n" not in after and "kept\r\n" not in after
    assert all(m in after for m in ("PROMPT COPY", "PROMPT REPLACE", "PROMPT DELETE", "CALL 0011 [x]"))
    state = {}  # moved / reintroduced lines point at the literals already read
    for n, text in enumerate(["alpha\nbeta\ngamma\n", "gamma\nalpha\nbeta\n", "alpha\n", "alpha\nbeta\ngamma\nnew ending"], 21):
        out = walk.emit_call(*call(tmp_path, n, "y", text), state, False)
        if n in (22, 24):
            assert not any(f"{w}\n" in out for w in ("alpha", "beta", "gamma")) and "CALL 0021 [y]" in out
    assert "new ending" in out

LUNA = {"walk-role": "4f6c460c8ab6f94e3eb2d0f337ebe9251c1320f2d02dc8e6a4d99f1a2b75a96e",
        "walk-reader": "203e1a04ba0ecc04c8965b665201517598b27ec13ad7a94bf883b8234d1df518",
        "walk-context": "74e15a2dc4554a477de105edad4ac3dc88824c82fe379b374790e068741151da"}
LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#([^)]*))?\)")

def test_walk_process_docs_route_reader_context_analysis_and_every_link_resolves():
    """Guidance has two homes feeding three byte-identical Luna inputs that bootstrap nothing; Stages route reading -> context
    -> analysis; retired docs are unnamed; every doc link and anchor resolves; the analyst (Sol) is never assigned."""
    walking, analysis = (DOCS / "walk-prompt.md").read_text(), (DOCS / "walk-analysis.md").read_text()
    assert {p.name for p in DOCS.glob("walk-*.md")} == {"walk-prompt.md", "walk-analysis.md", *(n + ".md" for n in LUNA)}
    for name, digest in LUNA.items():
        raw = (DOCS / f"{name}.md").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest and not LINK.search(raw.decode()) and f"{name}.md" in walking
    stages = re.search(r"^## Stages\n(.*?)(?=^## |\Z)", walking, re.M | re.S)[1]
    assert [list(dict.fromkeys(re.findall(r"\]\(([^)#]+\.md)", ln))) for ln in stages.splitlines() if re.match(r"\d+\. ", ln)] == [
        ["walk-reader.md"], ["walk-context.md"], ["walk-analysis.md"]]
    for doc in (DOCS / "walk-prompt.md", DOCS / "walk-analysis.md", ROOT / "suite/README.md", DOCS / "cell-loop-prompt.md", DOCS / "principles.md"):
        text = doc.read_text()
        assert not re.search(r"\bSol\b|walk-(controller|investigator|sol|guidance-walking|guidance-analysis)\.md", text), doc
        for target, anchor in LINK.findall(text):
            dest = (doc.parent / target).resolve()
            slugs = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^#+ (.+)$", dest.read_text(), re.M)}
            assert dest.is_file() and (not anchor or anchor in slugs), (doc.name, target, anchor)
    assert "../suite/README.md#closed-walk-and-fix-retention" in walking + analysis
