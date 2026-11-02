"""Walk output stays consistent."""
from pathlib import Path

from suite import walk

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
