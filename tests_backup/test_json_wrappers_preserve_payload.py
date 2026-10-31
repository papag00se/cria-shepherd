"""F06/F37: protocol framing cannot eat reserved strings inside valid JSON."""
import json

import pytest

from cria.config import Role
from cria.jsontext import close_unclosed_object, denoise, extract_json_object, strip_think


@pytest.mark.parametrize("literal", ["</think>", "<think>payload</think>", "```json payload```", "<think>unclosed", 'escaped "quotes" and </think>'])
@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "<think>private deliberation</think> {}"])
def test_actual_json_payload_bytes_survive_wrapper_removal(literal, wrapper):
    answer = {"done":False, "reason":literal, "nested":{"value":literal}}
    assert extract_json_object(wrapper.format(json.dumps(answer))) == answer


def test_nested_escapes_braces_fences_and_duplicate_keys_keep_exact_literal_bytes():
    literal = ('{\n  "done":false, "reason":"\\\"quoted\\\" {brace} </think> and '
               '<think>literal</think> ```json code```", "nested":{"items":["} </think>", '
               '"\\\\escaped", "<think>unclosed"]}, "done":true\n}')
    assert denoise(literal) == literal
    assert Role(name="judge", backend="local", reasoning="off").clean_content(literal) == literal
    assert extract_json_object(literal)["done"] is False
    assert denoise("```json\n" + literal + "\n```") == literal + "\n"


@pytest.mark.parametrize("middle", ["</think>", "<think>private deliberation</think>",
                                     "</thinking>", "</THINK >",
                                     "<THINKING>private deliberation</THINKING>"])
def test_common_parser_discards_earlier_private_json_before_real_outside_close(middle):
    private = json.dumps({"done": True, "reason": "private quote </think> is just data"})
    public = json.dumps({"done": False, "reason": "actual answer"})
    assert extract_json_object(private + middle + public) == {"done": False, "reason": "actual answer"}


@pytest.mark.parametrize("flag", ["done", "satisfied"])
@pytest.mark.parametrize("value", [False, True])
@pytest.mark.parametrize("fenced", [False, True])
def test_repairable_tail_literal_is_preserved_not_promoted_to_complete_answer(flag, value, fenced):
    answer = {flag:value, "reason":"Required output containing literal </think> and ```json is missing"}
    tail = json.dumps(answer)[:-1]
    text = "```json\n" + tail + "\n```" if fenced else tail
    assert denoise(text).strip() == tail
    assert Role(name="judge", backend="local", reasoning="off").clean_content(text) == text
    assert close_unclosed_object(text) == answer
    assert extract_json_object(text) is None
    private = json.dumps({flag:True, "reason":"private approval </think> quoted"})
    assert close_unclosed_object(private + "</think>" + text) == answer
    assert close_unclosed_object(tail[:-1]) is None  # missing quote is NOT missing braces


@pytest.mark.parametrize("flag", ["done", "satisfied"])
@pytest.mark.parametrize("fenced", [False, True])
def test_repairable_outer_boundary_does_not_promote_complete_descendant(flag, fenced):
    answer = {flag:False, "reason":"Required literal <think> is missing",
              "example":{flag:True, "reason":"illustration only"},
              "detail":"Required literal </think> is missing"}
    tail = json.dumps(answer)[:-1]
    text = "```json\n" + tail + "\n```" if fenced else tail
    assert denoise(text).strip() == tail
    assert extract_json_object(text) is None
    assert close_unclosed_object(text) == answer
    private = json.dumps({flag:True})
    assert extract_json_object(private + "</think>" + text) is None
    assert close_unclosed_object(private + "</think>" + text) == answer


def test_think_block_around_a_private_object_is_removed_not_promoted():
    private = json.dumps({"done":True, "reason":"quoted </think> is not the closing frame"})
    answer = {"done":False, "reason":"actual ruling"}
    text = "<think>" + private + "</think>" + json.dumps(answer)
    assert extract_json_object(text) == answer
    assert strip_think(text) == json.dumps(answer)


def test_repeated_boolean_keys_still_use_the_shared_first_nonempty_parser():
    text = '{"done":false,"reason":"literal </think>","done":true}'
    answer = {"done":False, "reason":"literal </think>"}
    cleaned = Role(name="judge", backend="local", reasoning="off").clean_content(text)
    assert extract_json_object(cleaned) == answer


def test_off_role_keeps_literal_markers_but_discards_real_unopened_prefix():
    role = Role(name="judge", backend="local", reasoning="off")
    answer = json.dumps({"done":False,"reason":"</think> literal"})
    assert role.clean_content(answer) == answer
    assert role.clean_content('private thinking</think>' + answer) == answer
    # Ordinary text and reasoning-ON role pass-through remain unchanged.
    assert role.clean_content('ordinary answer') == 'ordinary answer'
    assert Role(name="judge", backend="local", reasoning="on").clean_content('thinking</think>' + answer) == 'thinking</think>' + answer
