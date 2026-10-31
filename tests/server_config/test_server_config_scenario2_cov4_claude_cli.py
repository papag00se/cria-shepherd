"""The Claude-CLI backend through a real child process (a stand-in `claude` shell script): what the CLI prints is parsed into an OpenAI-shaped
completion whatever its shape, a failing or hung CLI is an UpstreamError the loop can act on, the session map stays bounded, and the
prompt is the latest user text only."""
import json
import stat

import pytest

from cria import claude_cli
from cria.claude_cli import ClaudeCliProvider
from cria.upstream import UpstreamError

BODY = {"model": "claude-x", "messages": [{"role": "user", "content": "first"}, {"role": "assistant", "content": "a"},
                                           {"role": "user", "content": "the real ask"}]}


class Rlog:
    def __init__(self, session):
        self.session, self.events = session, []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def fake(tmp_path, script, name="claude"):
    binary = tmp_path / name
    binary.write_text("#!/bin/sh\n" + script)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return str(binary)


def say(payload):
    return f"printf '%s' '{payload}'\n"


@pytest.mark.parametrize("stdout,content,model,tokens", [
    ('{"result":"done","model":"claude-real","usage":{"input_tokens":3,"output_tokens":4}}', "done", "claude-real", (3, 4)),
    ('{"content":"alt field"}', "alt field", "claude-x", (0, 0)),                    # `content` is the alternative; no usage → zeros
    ('{"result":7,"content":9}', "", "claude-x", (0, 0)),                            # neither is a string: empty, not "7"
    ('{"result":"x","usage":{"input_tokens":null,"output_tokens":"5"}}', "x", "claude-x", (0, 5)),
    ("plain text answer\n", "plain text answer", "claude-x", (0, 0)),               # unparseable stdout is the content
    ('["a list"]', '["a list"]', "claude-x", (0, 0)),                                # JSON but not an object: also the content
])
def test_whatever_the_cli_prints_becomes_one_openai_completion_with_honest_usage(tmp_path, stdout, content, model, tokens):
    provider = ClaudeCliProvider(binary=fake(tmp_path, say(stdout)))
    done = json.loads(provider.chat(BODY, Rlog(None)))
    assert done["object"] == "chat.completion" and done["model"] == model and done["choices"][0]["finish_reason"] == "stop"
    assert done["choices"][0]["message"] == {"role": "assistant", "content": content}
    assert (done["usage"]["prompt_tokens"], done["usage"]["completion_tokens"], done["usage"]["total_tokens"]) == (*tokens, sum(tokens))


def test_the_prompt_is_the_latest_user_text_and_a_stream_is_one_role_one_content_one_stop_then_done(tmp_path):
    seen = tmp_path / "args"
    binary = fake(tmp_path, f'printf "%s\\n" "$2|$4|$6" > "{seen}"\n' + say('{"result":"R"}'))
    provider = ClaudeCliProvider(binary=binary)
    chunks = list(provider.stream_chat(BODY, Rlog(None)))
    assert seen.read_text().strip() == "the real ask|claude-x|json"
    frames = [json.loads(c[6:]) for c in chunks[:-1]]
    assert [f["choices"][0]["delta"] for f in frames] == [{"role": "assistant"}, {"content": "R"}, {}] and frames[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1] == b"data: [DONE]\n\n"
    empty = list(ClaudeCliProvider(binary=fake(tmp_path, say("{}"), "empty")).stream_chat(BODY, Rlog(None)))
    assert len(empty) == 3 and all(b'"content"' not in c for c in empty)                  # no content frame for an empty result


def test_a_failing_cli_and_a_hung_cli_are_upstream_errors_with_the_cause_in_the_event_log(tmp_path):
    bad = Rlog("s")
    with pytest.raises(UpstreamError, match="claude CLI exited 3: out of credit"):
        ClaudeCliProvider(binary=fake(tmp_path, "echo 'out of credit' >&2; exit 3\n")).chat(BODY, bad)
    assert bad.events[-1][0] == "claude.error" and bad.events[-1][1]["code"] == 3 and bad.events[-1][1]["stderr"] == "out of credit\n"
    slow = Rlog("s")
    with pytest.raises(UpstreamError, match="timed out after 0.3s"):
        ClaudeCliProvider(binary=fake(tmp_path, "sleep 5\n", "slow"), timeout_seconds=0.3).chat(BODY, slow)
    assert slow.events[-1] == ("claude.error", {"level": "error", "error": "timeout"})
    missing = Rlog("s")
    with pytest.raises(UpstreamError, match="claude CLI not found"):
        ClaudeCliProvider(binary=str(tmp_path / "nope")).chat(BODY, missing)
    assert "binary not found" in missing.events[-1][1]["error"]


def test_the_resume_map_is_bounded_oldest_first_and_a_failed_call_leaves_it_untouched(tmp_path, monkeypatch):
    """With room for two sessions, the third evicts the first (which then starts FRESH again), and a CLI that errors does not record an id."""
    monkeypatch.setattr(claude_cli, "_MAX_CLI_SESSIONS", 2)
    log = tmp_path / "log"
    binary = fake(tmp_path, f'echo "$*" >> "{log}"\n' + say('{"result":"ok","session_id":"SID"}'))
    provider = ClaudeCliProvider(binary=binary)
    for session in ("a", "b", "c"):
        provider.chat(BODY, Rlog(session))
    assert list(provider._sessions) == ["b", "c"]
    provider.chat(BODY, Rlog("a"))                                                       # `a` was evicted: fresh, not a resume
    lines = log.read_text().splitlines()
    assert ["--resume" in line for line in lines] == [False, False, False, False] and list(provider._sessions) == ["c", "a"]
    provider.chat(BODY, Rlog("c"))
    assert "--resume SID" in log.read_text().splitlines()[-1]
    broken = ClaudeCliProvider(binary=fake(tmp_path, "exit 1\n", "broken"))
    with pytest.raises(UpstreamError):
        broken.chat(BODY, Rlog("z"))
    assert broken._sessions == {}
    fresh = ClaudeCliProvider(binary=binary)
    fresh.chat(BODY, Rlog(None))
    assert fresh._sessions == {}                                                         # a sessionless call remembers nothing to resume
