"""O9 (ornith1.5_9b / Java B2): the coder's ⟦ctx:files⟧ header said "older turns were compacted" on
every frame, even right after a successful write with nothing dropped. The coder concluded "the
workspace keeps getting reset" and rewrote Importer.java from scratch repeatedly. The claim may be
made only when the body actually carries a compaction (#5b)."""
import cria.loop as loop
from cria import selfcompact


def _body(extra=()):
    return [
        {"role": "user", "content": "Build the importer."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file", "arguments": "{}"}}]},
        {"role": "tool", "content": "Wrote src/main/java/pipeline/Importer.java"},
        *extra,
    ]


def _listing(tmp_path, msgs):
    (tmp_path / "Importer.java").write_text("class Importer {}")
    out = loop._ground_coder_view(msgs, str(tmp_path))
    return next(m["content"] for m in out if selfcompact._is_files_msg(m))


def test_no_compaction_no_compaction_claim(tmp_path):
    text = _listing(tmp_path, _body())
    assert "compacted" not in text
    assert "YOUR WORKSPACE SURVEY" in text and "names observed" in text
    assert "Importer.java (17 B)" in text
    assert "RIGHT NOW" not in text and "just now" not in text
    assert "Use read_file for file contents" in text
    assert "read it rather than reconstructing it from memory or from the summary" in text


def test_real_compaction_keeps_the_claim(tmp_path):
    for marker in ("⟦ctx:rollup⟧", "⟦ctx:briefing⟧", "⟦ctx:continuation⟧", "⟦ctx:compacted⟧ 27 earlier turn(s)"):
        text = _listing(tmp_path, _body([{"role": "user", "content": f"{marker} earlier work"}]))
        assert "older turns were compacted" in text, marker
