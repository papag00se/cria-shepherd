"""CLI contracts for lossless, independently readable section-local prompt reuse."""
import json
import re
from unittest import mock

import pytest

from suite import walk


_HEADERS = re.compile(r"^CALL (\d{4}) \[([^\n]+)\]$", re.MULTILINE)


def capture(root, number, phase, prompt, *, reasoning=None, arguments=None, partial=None):
    stem = root / f"{number:04d}-{phase}"
    stem.with_suffix(".json").write_text(json.dumps({"seq": number, "phase": phase}), encoding="utf-8")
    stem.with_suffix(".prompt.txt").write_bytes(prompt.encode("utf-8"))
    if reasoning is not None or arguments is not None:
        response = {"choices": [{"message": {
            "reasoning_content": reasoning or "",
            "content": f"answer-{number}",
            "tool_calls": [] if arguments is None else [{"function": {"name": "edit", "arguments": arguments}}],
        }, "finish_reason": "tool_calls"}]}
        stem.with_suffix(".response.json").write_text(json.dumps(response), encoding="utf-8")
    if partial is not None:
        (root / f"{stem.name}.json.reasoning.partial.txt").write_bytes(partial.encode("utf-8"))


def render(root, out, *options):
    with mock.patch("sys.argv", ["walk.py", str(root), "--out", str(out), *map(str, options)]):
        walk.main()
    manifest = json.loads((out / "assignments.json").read_text(encoding="utf-8"))
    sections = []
    assigned = []
    for section in manifest["segments"]:
        names = section["chunks"]
        assigned.extend(names)
        raw = b"".join((out / name).read_bytes() for name in names)
        assert section["bytes"] == len(raw), "section budget must measure actual emitted UTF-8"
        assert section["oversized"] == (len(raw) > manifest["segment_bytes_budget"])
        sections.append(raw.decode("utf-8"))
    assert len(assigned) == len(set(assigned)), "a chunk cannot belong to two independent readers"
    assert set(assigned) == {p.name for p in out.glob("chunk*.txt")}
    assert manifest["chunks_total"] == len(assigned)
    return manifest, sections


def call_blocks(text):
    headers = list(_HEADERS.finditer(text))
    return [(m.group(1), m.group(2), text[m.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)])
            for i, m in enumerate(headers)]


def assert_local_references(text):
    """Any CALL mentioned by a delta must already have appeared in this reader's section."""
    seen = {}
    for number, phase, body in call_blocks(text):
        for reference in re.finditer(r"\bCALL\s+(\d{4})\b", body):
            target = reference.group(1)
            assert target in seen, f"CALL {number} references unread/out-of-section CALL {target}"
            assert seen[target] == phase, "prompt reuse must follow the same phase, not the preceding call"
        seen[number] = phase


@pytest.mark.parametrize("budget_option", ["--segment-bytes", "--reader-context-tokens"])
def test_interleaved_phases_reuse_whole_lines_across_chunks(tmp_path, budget_option):
    root = tmp_path / "capture"
    root.mkdir()
    common = "".join(f"stable-{i:03d}: " + "界" * 30 + "\n" for i in range(45))
    for number, phase in [(1, "coder"), (2, "judge"), (3, "coder"), (4, "judge")]:
        capture(root, number, phase, f"{phase} baseline\n" + common + f"new whole line {number}\n")
    manifest, sections = render(root, tmp_path / "walk", budget_option, 50000, "--chunk-bytes", 1)
    assert len(sections) == 1
    assert len(manifest["segments"][0]["chunks"]) == 4, "reuse must survive chunk boundaries"
    text = sections[0]
    assert text.count(common) == 2, "each phase needs one baseline, not four full prompts"
    blocks = call_blocks(text)
    assert [n for n, _, _ in blocks] == ["0001", "0002", "0003", "0004"]
    for number, phase, body in blocks:
        assert f"new whole line {int(number)}\n" in body
        if int(number) <= 2:
            assert f"{phase} baseline\n{common}" in body
        else:
            assert re.search(r"\bCALL\s+\d{4}\b", body), "omission needs an explicit prior call"
            assert re.search(r"\blines?\b", body, re.IGNORECASE), "omission needs original line coordinates"
    assert_local_references(text)


def test_every_section_restarts_each_phase_and_never_shares_a_chunk(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prompts = {phase: f"{phase} independent baseline\n" + (f"{phase} unchanged payload 界\n" * 90)
               for phase in ("coder", "judge")}
    for number in range(1, 17):
        phase = "coder" if number % 2 else "judge"
        capture(root, number, phase, prompts[phase], reasoning=f"unique reasoning {number}\n" + "r" * 900)
    manifest, sections = render(root, tmp_path / "walk", "--segment-bytes", 11000,
                                "--chunk-bytes", 5000)
    assert len(sections) > 1, "fixture must exercise independent readers"
    all_numbers = []
    for section, text in zip(manifest["segments"], sections):
        assert section["bytes"] <= 11000
        seen = set()
        blocks = call_blocks(text)
        for number, phase, body in blocks:
            all_numbers.append(int(number))
            if phase not in seen:
                assert prompts[phase] in body, "first phase occurrence in EACH section must be full"
                assert not re.search(r"\bCALL\s+\d{4}\b", body)
                seen.add(phase)
        for phase in seen:
            assert text.count(prompts[phase]) == 1
        assert_local_references(text)
    assert all_numbers == list(range(1, 17)), "calls must remain whole and chronological"
    # Each chunk itself must start with a call, never a continuation cut from another chunk.
    for path in (tmp_path / "walk").glob("chunk*.txt"):
        assert _HEADERS.search(path.read_text(encoding="utf-8"))


def test_changed_middle_and_shrink_preserve_whole_new_lines_and_explain_removals(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prefix = "unchanged opening line\n"
    suffix = "unchanged trailing line\nlast surviving line\n"
    capture(root, 1, "coder", prefix + "setting = OLD\nremove this line\n" + suffix)
    capture(root, 2, "coder", prefix + "setting = NEW\nremove this line\n" + suffix)
    capture(root, 3, "coder", prefix + "setting = NEW\n" + suffix)
    _, sections = render(root, tmp_path / "walk", "--segment-bytes", 20000, "--chunk-bytes", 1)
    assert len(sections) == 1
    text = sections[0]
    assert text.count(prefix) == 1
    assert text.count(suffix) == 1, "unchanged suffixes must be referenced, not reprinted"
    _, changed, shrunk = call_blocks(text)
    assert "setting = NEW\n" in changed[2], "a mid-line change must emit the entire changed line"
    for body in (changed[2], shrunk[2]):
        assert re.search(r"\bCALL\s+\d{4}\b", body)
        assert re.search(r"\blines?\b", body, re.IGNORECASE)
    assert re.search(r"replac|delet|remov", changed[2], re.IGNORECASE), "replacement must be explicit"
    assert re.search(r"delet|remov", shrunk[2], re.IGNORECASE), "shrink must identify deleted lines"
    assert_local_references(text)


def test_full_prompts_is_an_explicit_opt_out_even_with_sectioning(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prompt = "verbatim full baseline\n" * 20
    for number in range(1, 4):
        capture(root, number, "coder", prompt)
    _, sections = render(root, tmp_path / "walk", "--segment-bytes", 20000, "--full-prompts")
    assert len(sections) == 1
    assert sections[0].count(prompt) == 3
    for _, _, body in call_blocks(sections[0]):
        assert not re.search(r"\bCALL\s+\d{4}\b", body)


def test_section_budget_uses_deduped_emission_not_whole_prompt_estimates(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prompt = "".join(f"source line {i}: " + "x" * 80 + "\n" for i in range(50))
    for number in range(1, 4):
        capture(root, number, "coder", prompt)
    manifest, sections = render(root, tmp_path / "walk", "--segment-bytes", 8000,
                                "--chunk-bytes", 1)
    assert len(prompt.encode("utf-8")) * 2 > 8000
    assert len(sections) == 1, "later reused prompts must not consume their original byte size"
    assert sections[0].count(prompt) == 1
    assert manifest["segments"][0]["bytes"] <= 8000


def test_utf8_section_boundary_overrides_a_larger_chunk_target(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prompt = "界" * 900 + "\n"
    capture(root, 1, "coder", prompt)
    capture(root, 2, "judge", prompt)
    manifest, sections = render(root, tmp_path / "walk", "--segment-bytes", 5000,
                                "--chunk-bytes", 50000)
    assert len(sections) == 2, "UTF-8 bytes, not characters or chunk size, determine reader boundaries"
    assert sum(map(len, sections)) < 5000, "fixture distinguishes byte and character budgeting"
    assert [len(call_blocks(text)) for text in sections] == [1, 1]
    assert all(prompt in text for text in sections)
    assert all(not section["oversized"] for section in manifest["segments"])
    assert all(len(section["chunks"]) == 1 for section in manifest["segments"])


def test_prompt_reuse_never_deduplicates_reasoning_arguments_or_stream_fragments(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    prompt = "prompt-only shared line\n" * 30
    reasoning = "complete reasoning 界\n" * 150 + "REASONING-END"
    arguments = json.dumps({"path": "界.txt", "content": "argument line\n" * 300 + "ARGS-END"}, ensure_ascii=False)
    partial = "unfinished stream 界\r\n" * 120 + "PARTIAL-END\n\n"
    for number in (1, 2):
        capture(root, number, "coder", prompt, reasoning=reasoning, arguments=arguments, partial=partial)
    _, sections = render(root, tmp_path / "walk", "--segment-bytes", 100000, "--chunk-bytes", 1)
    assert len(sections) == 1
    raw = sections[0].encode("utf-8")
    for evidence in (reasoning, arguments, partial):
        assert raw.count(evidence.encode("utf-8")) == 2
    assert sections[0].count(prompt) == 1
    assert sections[0].count("not a completed response") == 2
    assert sections[0].count("[finish: tool_calls]") == 2
    # One indivisible call exceeding a byte budget is a flagged section, not truncated evidence.
    manifest, tiny_sections = render(root, tmp_path / "tiny", "--segment-bytes", 1000,
                                     "--chunk-bytes", 1000)
    assert len(tiny_sections) == 2
    assert all(s["oversized"] for s in manifest["segments"])
    for text in tiny_sections:
        assert len(call_blocks(text)) == 1
        assert prompt in text, "even oversized sections restart the phase baseline"
        for evidence in (reasoning, arguments, partial):
            assert evidence.encode("utf-8") in text.encode("utf-8")
        assert_local_references(text)
