"""The un-protected half of the REAL Upstream wire (chat() over a fake llama.cpp): structural growth after the fit is re-fitted or refused with a truthful notice,
a guessed window never trims, the prefix-cache break is attributed per session, and the /props and /v1/models probes have a bounded retry budget."""
import json

import pytest

from cria import bodykeys, tokenratio
from cria import upstream as upstream_module
from cria.upstream import InputOverflow, Upstream
from test_context_wire_a_scenario3_cov3_readfit import Llama, fresh_density  # noqa: F401
from test_context_wire_a_stream import Rlog

QUOTES = '"' * 500


def malformed_history(n=3):
    """The task, `n` historical calls whose arguments are NOT JSON (a coder's botched call), then a new turn. The wire must envelope each - which GROWS it after the fit."""
    msgs = [{"role": "user", "content": "fix the bug"}]
    for i in range(n):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"o{i}", "type": "function", "function": {"name": "shell", "arguments": QUOTES}}]},
                 {"role": "tool", "tool_call_id": f"o{i}", "content": "ok"}]
    return msgs + [{"role": "user", "content": "go on"}]


class Recording(Llama):
    def __call__(self, req, timeout=None, receipt=None):
        self.sent = json.loads(req.data)
        return super().__call__(req, timeout, receipt)


def chat(llama, messages, window, rlog=None, **body):
    up = Upstream("http://llama.invalid", context_window=window, open_request=llama, engagement_level=5)
    rlog = rlog or Rlog()
    up.chat({"model": "m", "max_tokens": 300, "messages": messages, **body}, rlog)
    return rlog


def enveloped(messages):
    return [{**m, "tool_calls": [{**c, "function": {**c["function"], "arguments": json.dumps({"_unparsed": c["function"]["arguments"]})}} for c in m["tool_calls"]]}
            if m.get("tool_calls") else m for m in messages]


def test_a_wire_that_grows_after_the_fit_is_refitted_with_the_measured_growth_and_loses_no_text():
    """Enveloping 3 botched histories (each quote becomes \\\") doubles the estimate AFTER the floor fitted it. At 1,500 tokens the refit carries exactly that growth (final - fitted)
    and ships; every malformed argument arrives whole inside the envelope. A roomy window needs no refit."""
    roomy = chat(Recording(tokenizer=False), malformed_history(), 2400)
    assert roomy.first("context.wire_refit") is None
    llama, rlog = Recording(tokenizer=False), Rlog()
    chat(llama, malformed_history(), 1500, rlog)
    refit = rlog.first("context.wire_refit")
    assert refit["final_estimate"] > refit["fitted_estimate"] and refit["wire_overhead"] == refit["final_estimate"] - refit["fitted_estimate"]
    assert rlog.first("context.floor")["wire_overhead"] == refit["wire_overhead"]
    sent = [json.loads(c["function"]["arguments"]) for m in llama.sent["messages"] for c in m.get("tool_calls") or []]
    assert sent == [{"_unparsed": QUOTES}] * 3 and "chat" in llama.paths


@pytest.mark.parametrize("tokenizer,window", [(False, 1300), (True, 1200), (True, 900)])
def test_a_request_that_cannot_fit_even_after_the_refit_is_refused_with_its_size_and_nothing_is_sent(tokenizer, window):
    """Unmeasured: the estimate (about 1,391 tokens) is reported as an ESTIMATE; measured: the server's own count (the fake tokenizer: 3 characters a token of the final prompt).
    Either way the notice says nothing was cut or processed, and the model server never sees the request."""
    llama = Recording(tokenizer=tokenizer)
    with pytest.raises(InputOverflow) as err:
        chat(llama, malformed_history(), window)
    final = json.dumps(enveloped(malformed_history()))
    assert err.value.measured is tokenizer and err.value.window == window and "chat" not in llama.paths
    assert err.value.tokens == (len(final) // 3 if tokenizer else 1391)
    notice = err.value.notice()
    assert ("estimated at about 1,391 tokens" if not tokenizer else f"measured {len(final) // 3:,} tokens") in notice and "Nothing was cut, summarised or dropped" in notice


def test_a_guessed_window_never_trims_and_the_unreadable_props_are_retried_on_a_budget():
    """/props unreadable -> the 8,192 fallback is a GUESS: a 12,000-token conversation ships whole (the server settles it), the skip is logged, and the probe stops after 3 misses
    except every 50th call; when the server finally answers, the real window (and the floor) applies."""
    big = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "a" * 20000}, {"role": "user", "content": "second"}]
    llama, rlog = Recording(props=False), Rlog()
    up = Upstream("http://llama.invalid", open_request=llama, engagement_level=5)
    for _ in range(120):
        up.chat({"model": "m", "messages": big}, rlog)
    assert llama.paths.count("props") == 3 + 2 and len(llama.sent["messages"]) == 3 and llama.sent["messages"][1]["content"] == "a" * 20000
    assert rlog.first("context.floor_skipped")["guess"] == 8192 and not [1 for k, _ in rlog.events if k == "context.floor"]
    assert [f["source"] for k, f in rlog.events if k == "context.window" and f.get("level") == "warn"] == ["fallback"]
    llama.props = True
    llama.window = 4096
    for _ in range(50):
        up.chat({"model": "m", "messages": big}, rlog)
    assert llama.paths.count("props") == 3 + 2 + 1 and "⟦ctx:compacted⟧" in llama.sent["messages"][0]["content"] + llama.sent["messages"][1]["content"] and llama.sent["messages"][-1]["content"] == "second"


def test_a_props_without_a_context_size_is_a_miss_not_a_window():
    """/props that answers without n_ctx teaches nothing: logged as such, the window stays a guess."""
    class NoCtx(Recording):
        def ordinary(self, req, timeout=None):
            return super().ordinary(req, timeout) if not req.full_url.endswith("props") else type(super().ordinary(req, timeout))({"default_generation_settings": {}})
    rlog = chat(NoCtx(), [{"role": "user", "content": "hi"}], None)
    assert rlog.first("context.window")["error"] == "no n_ctx in /props"


def test_the_loaded_model_probe_is_bounded_and_recovers_when_the_server_finishes_loading():
    """A server still loading refuses /v1/models: 1 first probe + 3 retries + one every 50th call (not one per request); when it answers the id is learned and never probed again."""
    class Loading(Llama):
        up = False

        def ordinary(self, req, timeout=None):
            if req.full_url.endswith("/v1/models"):
                self.paths.append("models")
                if not self.up:
                    raise OSError("loading")
                return type(super().ordinary(req.__class__("http://x/props"), timeout))({"data": [{"id": "served-model"}]})
            return super().ordinary(req, timeout)
    llama, rlog = Loading(), Rlog()
    up = Upstream("http://llama.invalid", open_request=llama)
    assert [up.loaded_model(rlog) for _ in range(120)] == [None] * 120 and llama.paths.count("models") == 1 + 3 + 2
    llama.up = True
    answers = [up.loaded_model(rlog) for _ in range(60)]
    first = answers.index("served-model")       # attempts 120..149 are skipped; the 150th call's probe succeeds
    assert first == 30 and answers[:first] == [None] * 30 and set(answers[first:]) == {"served-model"} and llama.paths.count("models") == 1 + 3 + 2 + 1
    assert [e for k, e in rlog.events if k == "upstream.models"][0]["error"] == "loading"


def test_the_prefix_cache_break_is_attributed_per_session_and_a_forgotten_session_starts_over(monkeypatch):
    """context.prefix names why this request's prefix differs from the same session's previous one - identical, append, tools, phase, an edited earlier message, a floor
    reduction (naming the compaction marker) - and another session's traffic never changes the answer; past the session cap the oldest session is forgotten."""
    llama = Recording()
    up = Upstream("http://llama.invalid", context_window=4096, open_request=llama, engagement_level=5)

    def turn(session, messages, phase="coder-main", **extra):
        log = Rlog()
        log.session, log.phase = session, phase
        up.chat({"model": "m", "max_tokens": 300, "messages": messages, **extra}, log)
        return log.first("context.prefix")
    base = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "go"}]
    grown = base + [{"role": "assistant", "content": "done"}, {"role": "user", "content": "more"}]
    tools = [{"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {}}}}]
    edited = [{"role": "user", "content": "task (edited)"}, *grown[1:]]
    later = grown + [{"role": "assistant", "content": "again"}, {"role": "user", "content": "last"}]
    flood = [*edited, {"role": "assistant", "content": None, "tool_calls": [{"id": "t", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "t", "content": "w" * 9000}, {"role": "user", "content": "now?"}]
    seen = [turn("s1", base)["reason"], turn("other", edited)["reason"], turn("s1", base)["reason"], turn("s1", grown)["reason"], turn("s1", grown, tools=tools)["reason"],
            turn("s1", later, "summarizer", tools=tools)["reason"], turn("s1", edited, "summarizer", tools=tools)["reason"]]
    assert seen == ["no_previous_request", "no_previous_request", "identical", "append", "tools_changed", "phase_changed", "input_changed"]
    reduced = turn("s1", flood, "summarizer", tools=tools)
    assert reduced["reason"] == "history_reduced" and reduced["break_source"] == "floor" and reduced["marker"] == "⟦ctx:compacted⟧"
    monkeypatch.setattr(upstream_module, "_MAX_PREFIX_SESSIONS", 1)
    turn("s2", base)
    assert turn("s1", base)["reason"] == "no_previous_request" and turn("s1", base)["reason"] == "identical"
