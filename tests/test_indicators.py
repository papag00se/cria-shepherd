import json
import unittest

from cria.indicators import (
    MARKER,
    Indicator,
    inject_buffered,
    strip_history,
    wrap_stream,
)


def _sse(delta: dict) -> bytes:
    return b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n\n"


def _model_stream(contents: list[str]) -> list[bytes]:
    out = [_sse({"role": "assistant"})]
    out += [_sse({"content": c}) for c in contents]
    out += [_sse({"finish_reason": "stop"}), b"data: [DONE]\n\n"]
    return out


def _assemble(chunks) -> str:
    """Reconstruct the message content a client would show from the SSE chunks."""
    text = []
    for raw in chunks:
        if not raw.startswith(b"data:"):
            continue
        payload = raw[5:].strip()
        if payload == b"[DONE]":
            continue
        for ch in json.loads(payload).get("choices", []):
            c = (ch.get("delta") or {}).get("content")
            if c:
                text.append(c)
    return "".join(text)


def _indic(**kw) -> Indicator:
    base = dict(enabled=True, metrics=True, model="fabliq_8b_reasoning_q6", role="coder", show_route=True)
    base.update(kw)
    return Indicator(**base)


class InjectStripRoundtrip(unittest.TestCase):
    def test_human_sees_it_model_does_not(self):
        # Inject on the way out...
        wrapped = list(wrap_stream(iter(_model_stream(["Hello", ", ", "world"])), _indic()))
        shown = _assemble(wrapped)
        self.assertTrue(shown.startswith(MARKER + "coder · fabliq_8b_reasoning_q6"))
        self.assertIn("Hello, world", shown)
        self.assertIn("tok/s", shown)  # 3 deltas → metrics line present

        # ...then codex records that as the assistant message and sends it back;
        # cria strips its own lines before the model sees them.
        clean, stripped = strip_history([{"role": "assistant", "content": shown}])
        self.assertEqual(clean[0]["content"], "Hello, world")  # only the model's text remains
        self.assertEqual(stripped, 2)  # route line + metrics line removed

    def test_metrics_suppressed_for_tiny_stream(self):
        # e.g. the Claude provider fake-streams one big chunk → no meaningful rate.
        wrapped = list(wrap_stream(iter(_model_stream(["everything at once"])), _indic()))
        self.assertNotIn("tok/s", _assemble(wrapped))
        self.assertIn(MARKER + "coder", _assemble(wrapped))  # route line still shown

    def test_disabled_is_pure_passthrough(self):
        stream = _model_stream(["a", "b", "c"])
        self.assertEqual(list(wrap_stream(iter(stream), _indic(enabled=False))), stream)

    def test_show_route_false_gives_metrics_only(self):
        shown = _assemble(list(wrap_stream(iter(_model_stream(["a", "b", "c", "d"])), _indic(show_route=False))))
        self.assertNotIn("coder ·", shown)  # no route line
        self.assertIn("tok/s", shown)  # but metrics


class StripTests(unittest.TestCase):
    def test_strips_only_marker_lines(self):
        content = f"{MARKER}coder · m\nreal answer line 1\nreal answer line 2\n{MARKER}12 tok · 5.0 tok/s"
        clean, n = strip_history([{"role": "assistant", "content": content}])
        self.assertEqual(clean[0]["content"], "real answer line 1\nreal answer line 2")
        self.assertEqual(n, 2)

    def test_leaves_clean_messages_untouched(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "no markers here"}]
        clean, n = strip_history(msgs)
        self.assertEqual(clean, msgs)
        self.assertEqual(n, 0)

    def test_tolerates_non_string_content(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
        clean, n = strip_history(msgs)  # must not raise
        self.assertEqual(n, 0)


class BufferedTests(unittest.TestCase):
    def test_prepends_route_line(self):
        raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "the answer"}}]}).encode()
        out = json.loads(inject_buffered(raw, _indic()))
        self.assertTrue(out["choices"][0]["message"]["content"].startswith(MARKER + "coder"))
        self.assertIn("the answer", out["choices"][0]["message"]["content"])

    def test_disabled_unchanged(self):
        raw = json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()
        self.assertEqual(inject_buffered(raw, _indic(enabled=False)), raw)

    def test_empty_content_gets_no_banner(self):
        # a header-only completion becomes a fake "response" — it once became an entire
        # compaction handoff summary. Empty content stays empty.
        for empty in ("", "   ", None):
            raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": empty}}]}).encode()
            out = json.loads(inject_buffered(raw, _indic()))
            self.assertEqual((out["choices"][0]["message"].get("content") or "").strip(), "")


if __name__ == "__main__":
    unittest.main()


class ToggleTests(unittest.TestCase):
    def test_route_false_omits_the_route_line(self):
        shown = _assemble(list(wrap_stream(iter(_model_stream(["a", "b", "c"])), _indic(route=False))))
        self.assertNotIn("coder · fabliq_8b_reasoning_q6", shown)  # route banner off
        self.assertIn("abc", shown)                                 # model text untouched

    def test_assists_false_omits_the_note(self):
        shown = _assemble(list(wrap_stream(
            iter(_model_stream(["a", "b", "c"])), _indic(assists=False, note="running the repo's checks"))))
        self.assertNotIn("running the repo's checks", shown)

    def test_strip_note_lines_drops_cria_notes_keeps_real_text(self):
        from cria.indicators import strip_note_lines, MARKER
        comp = {"choices": [{"message": {"content": f"{MARKER}running the repo's checks\nreal answer"}}]}
        strip_note_lines(comp)
        self.assertEqual(comp["choices"][0]["message"]["content"], "real answer")
