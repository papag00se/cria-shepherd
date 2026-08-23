"""cria must not tell the coder it already ran something cria itself refused.

`_visible_web_calls` harvests assistant `web_search` / `web_fetch` tool_calls to decide what result is
"still present in the conversation". A refused call is still an assistant tool_call — so a query cria
blocked was recorded as one the coder had run, and the next attempt was refused with "You already ran
web_search … Its results are already in this conversation above — use them." The query never ran and
the results exist nowhere.

Walked on shipping-rates-rb x nemotron-elastic 1787432916, three refusals deep on one query. The
sibling branch — the one naming a spill file — already carries a comment describing this same failure
costing 8 refusals in an earlier run; that fix was applied there and not here."""
import unittest

from cria import denial
from cria.server import _visible_web_calls


def _call(cid, name, args):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}]}


def _result(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


class OnlyWhatActuallyRanTests(unittest.TestCase):
    def test_a_refused_search_is_not_a_search_that_ran(self):
        msgs = [_call("c1", "web_search", '{"query":"refused one"}'),
                _result("c1", denial.mark("You already ran web_search …"))]
        self.assertEqual(_visible_web_calls(msgs)[1], [])

    def test_a_search_that_ran_is_still_counted(self):
        msgs = [_call("c1", "web_search", '{"query":"real one"}'),
                _result("c1", "Search results for: real one\n1. a thing")]
        self.assertEqual(_visible_web_calls(msgs)[1], ["real one"])

    def test_the_same_holds_for_a_refused_fetch(self):
        msgs = [_call("c1", "web_fetch", '{"url":"https://x/no"}'),
                _result("c1", denial.mark("refused")),
                _call("c2", "web_fetch", '{"url":"https://x/ok"}'),
                _result("c2", "HTTP 200 · https://x/ok")]
        self.assertEqual(_visible_web_calls(msgs)[0], [("https://x/ok", "", "")])

    def test_a_call_with_no_result_yet_is_left_alone(self):
        """Only a REFUSAL disqualifies. An in-flight call is not evidence of anything either way."""
        msgs = [_call("c1", "web_search", '{"query":"pending"}')]
        self.assertEqual(_visible_web_calls(msgs)[1], ["pending"])


if __name__ == "__main__":
    unittest.main()
