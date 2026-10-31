"""The coder frame carries a Chat caller's system text behind cria's own coder prompt (wave 9, agent L)."""
from cria import bodykeys, prompts
from cria.loop import _frame_for_item
from cria.server import carry_chat_system

SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "string"}}}}}
PERSONA = "You are a pirate assistant. Sign every message 'Arr!'."


def frame(messages):
    body = {"messages": messages}
    carry_chat_system(body)
    return _frame_for_item(body["messages"], "IGNORED", "", 1, 1, tools=[SHELL], synthetic=True)


def test_a_chat_callers_system_text_rides_in_the_coder_system_message_after_crias_own_prompt():
    """Before: the persona was dropped here without a word. Now: cria's coder prompt still leads (its safety/tool rules are
    not displaced), the caller's text follows in the same single system message with its persona span anchored, and the
    conversation after it is unchanged."""
    user = [{"role": "user", "content": "Add a --verbose flag."}]
    out = frame([{"role": "system", "content": PERSONA}, {"role": "developer", "content": "Never edit vendor/."}, *user])
    system = out[0]["content"]
    assert system.startswith(prompts.load("coder_system")) and PERSONA in system and "Never edit vendor/." in system
    assert system.index(PERSONA) > len(prompts.load("coder_system"))
    span = out[0][bodykeys.CALLER_SPAN]
    assert system[span["start"]:span["start"] + len(span["text"])] == PERSONA
    assert [m["role"] for m in out].count("system") == 1 and out[1:] == user


def test_a_chat_request_with_no_system_message_frames_exactly_as_before():
    """Byte-identical for callers that send none."""
    user = [{"role": "user", "content": "Add a --verbose flag."}]
    assert frame(user) == _frame_for_item(user, "IGNORED", "", 1, 1, tools=[SHELL], synthetic=True)
    assert frame(user)[0]["content"].startswith(prompts.load("coder_system")) and bodykeys.CALLER_SPAN not in frame(user)[0]
