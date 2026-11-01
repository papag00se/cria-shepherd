"""memoryhandoff (mutation-found gaps): the typed lifecycle selection, and the two message-text readers every handoff stage uses."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cria import memoryhandoff as mh

OTHER_POLICY = replace(mh.POLICY, id="some-other-assist", stage="other-stage")
UNRELATED = SimpleNamespace(policy=OTHER_POLICY)                          # not a handoff and not ours: never selected, never an error


@pytest.mark.parametrize("definitions,outcome", [
    ([], None), ([UNRELATED], None), ([UNRELATED, mh.DEFINITION, UNRELATED], mh.DEFINITION),
    ([mh.DEFINITION, mh.DEFINITION], "Duplicate harness memory handoff selection"),
    ([replace(mh.DEFINITION, policy=OTHER_POLICY)], "typed lifecycle contract"),            # a handoff that swaps its policy is refused, not skipped
    ([replace(mh.DEFINITION, recognize=None)], "typed lifecycle contract"),
    ([replace(mh.DEFINITION, frame="x")], "typed lifecycle contract"),
    ([replace(mh.DEFINITION, execute=None)], "typed lifecycle contract"),
    ([SimpleNamespace(policy=mh.POLICY)], "typed lifecycle contract")])                    # something wearing OUR policy that is not a handoff
def test_the_handoff_selection_is_exactly_one_compatible_lifecycle_and_never_a_default(definitions, outcome):
    if outcome is None or outcome is mh.DEFINITION:
        assert mh.selected_definition(definitions) is outcome
    else:
        with pytest.raises(ValueError, match=outcome):
            mh.selected_definition(definitions)


def test_message_text_joins_every_text_part_and_the_latest_user_turn_skips_everything_that_is_not_a_user_dict():
    parts = {"role": "user", "content": [{"text": "one"}, "junk", {"type": "image"}, {"text": "two"}]}
    assert mh.text_of_message(parts) == "one  two" and mh.text_of_message({"content": "plain"}) == "plain"
    assert mh.text_of_message({"content": None}) == "" and mh.text_of_message({"content": 7}) == ""
    history = [{"role": "user", "content": "first"}, parts, {"role": "assistant", "content": "answer"}, "not a message", None]
    assert mh.latest_user_text(history) == "one  two" and mh.latest_user_text([history[2]]) == ""
    assert mh.latest_user_text(None) == "" and mh.latest_user_text([{"role": "tool", "content": "x"}, {"role": "user", "content": "u"}]) == "u"
