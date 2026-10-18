"""A saved stream fragment is walk evidence, never a fabricated completed response."""
import json
from unittest import mock

from cria.upstream import Upstream
from suite import walk


def capture(root, number, phase="coder-s1", prompt="prompt\n", partial=None, response=None):
    stem = root / f"{number:04d}-{phase}"
    meta = root / f"{stem.name}.json"
    meta.write_text(json.dumps({"seq": number, "phase": phase}), encoding="utf-8")
    (root / f"{stem.name}.prompt.txt").write_bytes(prompt.encode("utf-8"))
    if partial is not None:
        # Authoritative producer spelling includes the metadata file's .json, not just its stem.
        from pathlib import Path
        Path(Upstream._partial_path(str(meta))).write_bytes(partial.encode("utf-8"))
    if response is not None:
        (root / f"{stem.name}.response.json").write_text(json.dumps(response), encoding="utf-8")
    return stem


def completed():
    return {"choices": [{"message": {
        "reasoning_content": "finished thought", "content": "finished answer",
        "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path":"x"}'}}],
    }, "finish_reason": "tool_calls"}]}


def emit(stem, previous=None, full=False):
    number, phase = stem.name.split("-", 1)
    return walk.emit_call(number, phase, stem, {} if previous is None else previous, full)


def test_final_0208_without_response_walks_the_entire_saved_fragment(tmp_path):
    # Same producer shape as B4's final 0208: metadata + prompt + .json.reasoning.partial.txt,
    # no response.json. Multiple final newlines and CRLF are meaningful saved bytes too.
    partial = "α full thought\r\n" + "reasoning line\n" * 625 + "unfinished `\t\n\n"
    stem = capture(tmp_path, 208, partial=partial)
    out = emit(stem)
    raw = partial.encode("utf-8")
    assert raw in out.encode("utf-8")
    assert out.count(partial) == 1
    assert "UNFINISHED STREAMED REASONING" in out
    assert "0208-coder-s1.json.reasoning.partial.txt" in out
    assert f"{len(raw)} bytes" in out
    assert "not a completed response" in out
    assert "[no response captured]" in out
    assert "--- SAY" not in out
    assert "--- TOOL CALL" not in out
    assert "[finish:" not in out


def test_complete_response_without_partial_retains_existing_voice(tmp_path):
    out = emit(capture(tmp_path, 1, response=completed()))
    assert "--- THINK (full) ---\nfinished thought" in out
    assert "--- SAY (full) ---\nfinished answer" in out
    assert '--- TOOL CALL read_file (full args) ---\n{"path":"x"}' in out
    assert "[finish: tool_calls]" in out
    assert "UNFINISHED" not in out
    assert "[no response captured]" not in out


def test_missing_response_and_partial_stays_distinct(tmp_path):
    out = emit(capture(tmp_path, 1))
    assert "[no response captured]" in out
    assert "UNFINISHED" not in out
    assert "--- THINK" not in out
    assert "[finish:" not in out


def test_partial_and_complete_response_coexist_without_replacing_either(tmp_path):
    fragment = "saved stream prefix\r\n\n"
    out = emit(capture(tmp_path, 1, partial=fragment, response=completed()))
    assert out.count(fragment) == 1
    assert out.index(fragment) < out.index("--- THINK (full) ---")
    assert "not a completed response" in out
    assert "finished thought" in out and "finished answer" in out
    assert "[finish: tool_calls]" in out
    assert "[no response captured]" not in out


def test_multiple_calls_are_ordered_and_partial_does_not_break_prompt_reconstruction(tmp_path):
    first = capture(tmp_path, 2, prompt="shared prompt\nfirst\n", partial="first fragment\n")
    second = capture(tmp_path, 10, prompt="shared prompt\nsecond\n", response=completed())
    other = capture(tmp_path, 3, phase="satisfaction", prompt="other phase\n", partial="other fragment")
    calls = walk.list_calls(tmp_path)
    assert [num for num, _, _ in calls] == ["0002", "0003", "0010"]
    prev = {}
    a, b, c = emit(first, prev), emit(other, prev), emit(second, prev)
    assert "--- PROMPT Δ ---\nsecond" in c
    assert "shared prompt\nfirst" in a
    assert prev == {"coder-s1": "shared prompt\nsecond\n", "satisfaction": "other phase\n"}
    assert "first fragment\n" in a and "other fragment" in b
    assert "UNFINISHED" not in c


def test_chunks_and_assignment_segments_cover_partial_bytes_with_whole_prompts(tmp_path, capsys):
    root = tmp_path / "capture"
    root.mkdir()
    fragment = "終\r\n" * 630 + "EOF-with-no-newline"
    capture(root, 1, prompt="shared prompt\nfirst\n", response=completed())
    capture(root, 2, prompt="shared prompt\nsecond\n", partial=fragment)
    capture(root, 3, phase="satisfaction", prompt="judge\n", response=completed())
    outdir = tmp_path / "walk"
    # Each whole call is a chunk; the big partial must count, become oversized and be assigned.
    with mock.patch("sys.argv", ["walk.py", str(root), "--out", str(outdir),
                                  "--chunk-bytes", "1500", "--chunk-lines", "100",
                                  "--segment-bytes", "1500"]):
        walk.main()
    stdout = capsys.readouterr().out
    chunks = sorted(outdir.glob("chunk*.txt"))
    assert len(chunks) == 3
    text = b"".join(p.read_bytes() for p in chunks)
    assert fragment.encode("utf-8") in text
    assert text.index(b"CALL 0001") < text.index(b"CALL 0002") < text.index(b"CALL 0003")
    assert b"shared prompt\nsecond\n" in chunks[1].read_bytes()
    assert b"PROMPT "+"Δ".encode() not in text
    manifest = json.loads((outdir / "assignments.json").read_text())
    names = [name for s in manifest["segments"] for name in s["chunks"]]
    assert names == [p.name for p in chunks]
    for segment in manifest["segments"]:
        actual = sum((outdir / name).stat().st_size for name in segment["chunks"])
        assert segment["bytes"] == actual
    assert sum(s["bytes"] for s in manifest["segments"]) == len(text)
    assert manifest["segments"][1]["oversized"] is True
    assert "OVERSIZED chunk02.txt" in stdout
    assert "PAGE IT" in stdout
    assert not (outdir / "WALK-PLAN.md").exists()
    assert not list((outdir / "findings").iterdir())


def test_utf8_bytes_not_character_count_decide_chunk_and_segment_boundaries(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    stem1 = capture(root, 1, prompt="p", partial="界" * 1000)
    stem2 = capture(root, 2, prompt="p", partial="界" * 1000)
    blocks = [emit(stem1, full=True), emit(stem2, full=True)]
    budget = max(len(b.encode("utf-8")) for b in blocks)
    assert sum(len(b) for b in blocks) <= budget
    outdir = tmp_path / "walk"
    with mock.patch("sys.argv", ["walk.py", str(root), "--out", str(outdir),
                                  "--chunk-bytes", str(budget), "--segment-bytes", str(budget)]):
        walk.main()
    chunks = sorted(outdir.glob("chunk*.txt"))
    assert len(chunks) == 2
    assert [p.read_bytes() for p in chunks] == [b.encode("utf-8") for b in blocks]
    manifest = json.loads((outdir / "assignments.json").read_text())
    assert [s["bytes"] for s in manifest["segments"]] == [p.stat().st_size for p in chunks]
