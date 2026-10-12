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
    assert "this list says which files exist" in text and "Importer.java" in text
    assert "Every file above is readable with read_file" in text


def test_real_compaction_keeps_the_claim(tmp_path):
    for marker in ("⟦ctx:rollup⟧", "⟦ctx:briefing⟧", "⟦ctx:continuation⟧", "⟦ctx:compacted⟧ 27 earlier turn(s)"):
        text = _listing(tmp_path, _body([{"role": "user", "content": f"{marker} earlier work"}]))
        assert "older turns were compacted" in text, marker
