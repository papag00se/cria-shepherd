"""The steer funnel (loop._vet_steer): an authored directive may not state a fact cria can refute.
Refusal is whole (never hollowed or reworded) and names the guard; a correct directive must pass untouched."""

import pytest

from cria import loop
from cria.fetchfacts import Shape
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

GO_SUM = ("$ go vet ./... — cart.go:8: missing go.sum entry for module providing package "
          "github.com/shopspring/decimal (imported by cartsvc); to add:\n\tgo get cartsvc\n")
USAGE = "go: errors parsing go.mod:\ngo.mod:4:5: usage: require module/path v1.2.3\n"
SHAPES = (Shape("GET /handles/{handle}", route="/handles/{handle}", fields=("hex", "name", "resolved_addresses", "ada")),
          Shape("GET /holders/{address}", route="/holders/{address}", fields=("total_handles", "address")))
LEDGER = {"https://api.handle.me/openapi.json": ("HTTP 200", (), SHAPES, ())}
ANSWERED = {"https://api.handle.me/handles/goose": ("HTTP 200 OK", ("/handles/{handle}",), (), (), "")}
# ada-handles_mellum2 1785714194 call 0026: blamed the service although cria held a 200 for it.
BLAME = "The API does not support /holders/{address}: it consistently returns 404, which is impossible given the API."


class Sess:
    def __init__(self, pages=None):
        self.fetched_pages, self.last_gate_flag = pages or {}, ""


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "rates.py").write_text("def zone_for(code):\n    return code\n" * 3)
    return str(tmp_path)


def vet(directive, evidence="", ws=None, sess=None, ask=None, messages=None):
    return loop._vet_steer(directive, evidence, Rlog(), ask, sess, [] if messages is None else messages, ws)


@pytest.mark.parametrize("directive, evidence, kw, guard", [
    ("Replace it with require github.com/shopspring/decimal v0.0.0-20240817123456-001 now.", GO_SUM, {},
     "invented_version"),                       # cart-billing-go cell 20: a pseudo-version the author made up
    ("Fix go.mod line 4: the format is `require module/path v1.2.3`.", USAGE, {}, "invented_version"),  # a usage synopsis is no evidence
    ("The real spec at /home/user1/.cache/api.handle.me/openapi.json lists it.", "", {}, "phantom_path"),
    ("Rename `nowhere` in rates.py to something else.", "", {}, "phantom_symbol"),
    ("The bug is at rates.py:999.", "", {}, "false_citation"),
    ("resolved_address = data.get('address')\n    total_holders = data.get('total_holders')", "evidence",
     {"sess": Sess(LEDGER)}, "phantom_field"),  # maple-preview 1786053138: a field cria's own parsed shapes lack
    (BLAME, "evidence", {"sess": Sess(ANSWERED), "ask": lambda s, u="": "BLAMES"}, "blames_a_service"),
], ids=["pseudo-version", "usage-synopsis", "system-path", "symbol-in-file", "line-citation", "response-field", "blames-service"])
def test_an_authored_claim_cria_can_refute_is_withheld_whole(directive, evidence, kw, guard, ws):
    """Each refutable claim is refused by guard name; the steer is None."""
    assert vet(directive, evidence, ws=ws, **kw) == (None, guard)


def test_a_grounded_directive_is_delivered_untouched(ws):
    """The same guards must not eat the correct directive: a false refusal leaves the coder stuck."""
    gemma = 'Fix the mock key: "resolved": data.get("resolved_addresses", {}).get("ada"),'
    grounded = [
        ("Run go get github.com/shopspring/decimal, then go mod tidy.", GO_SUM, {}),
        ("go.mod must require decimal v1.4.0 and rebuild.", GO_SUM + "go list -m: decimal v1.4.0\n", {}),  # a reported version
        ("Total is 48.58 but you print 44.98; 7 tests ran in 0.42 seconds.", "", {}),                       # not versions
        ("Pin it to 1.2.3 and rebuild.", "disk usage 1.2.3 GB high", {}),                                   # 'usage' inside a word
        ("Read /usr/bin/env semantics.", "", {}), ("Rename `zone_for` in rates.py; see rates.py:2.", "", {}),
        (gemma, "evidence", {"sess": Sess(LEDGER), "ask": lambda s, u="": "DESCRIBES"}),                    # gemma4 4/4
        (BLAME, "evidence", {"sess": Sess(ANSWERED), "ask": lambda s, u="": "GROUNDED"}),
        (BLAME, "evidence", {"sess": Sess(ANSWERED), "ask": lambda s, u="": "maybe"}),                      # unreadable keeps the steer
    ]
    for directive, evidence, kw in grounded:
        assert vet(directive, evidence, ws=ws, **kw) == (directive, ""), directive


def test_the_blame_check_costs_no_question_without_a_disproof():
    """No successful fetch, no reasoner, or plain prose: cria cannot disprove, so it asks nothing and keeps the steer."""
    asked = []
    ask = lambda s, u="": asked.append(s) or "BLAMES"  # noqa: E731
    assert vet(BLAME, sess=Sess({"https://x/h": ("HTTP 503", (), (), (), "")}), ask=ask)[0] == BLAME
    assert vet("Read the file before you rewrite it.", sess=Sess(ANSWERED), ask=ask)[0]
    assert vet(BLAME, sess=Sess(ANSWERED), ask=None)[0] == BLAME
    assert asked == []


# rust-toml-cli x ternary-bonsai 0015: the old strip shipped "Change [code removed] to [code removed]".
PRESCRIPTION = "Read src/main.rs: **Line 12**: `map.get(key)` fails on `String` keys. Change to `map.get(&key.to_string())`."
QUOTE = "Your line `map.get(key)` is what the compiler rejects. Read src/main.rs:12."
OBSERVED = [{"role": "tool", "tool_call_id": "c1", "content": "src/main.rs:12: error[E0308]\n   map.get(key)"}]


def test_invented_code_is_withheld_whole_but_the_coders_own_observed_line_ships():
    """A DICTATES verdict over code cria never observed withholds; code it observed is a quote."""
    ask = lambda s, u="": "DICTATES"  # noqa: E731
    assert vet(PRESCRIPTION, ask=ask, messages=OBSERVED) == (None, "dictated_code")
    assert vet(QUOTE, ask=ask, messages=OBSERVED) == (QUOTE, "")


def test_the_dictation_trigger_sees_calls_in_any_language_and_not_prose():
    """shipping-rates-rb 1787111689: Ruby `key?(` and Rust `::`/`!(` calls were invisible, so a paste-ready steer shipped."""
    code = ["zone = ZONE_BASE.key?(code) ? code : zone_for(code) then run rake", "rec.save!(true)", 'println!("hello")',
            "Replace let j = serde_json::to_string(&value); must be true.", "use serde_json::to_string(&v) instead"]
    prose = ["The rate table lists every zone with its base rate.", "Shipping.zone_for is missing for two-letter codes.",
             "Fix the loading; the code that uses it is not what failed here."]
    ask = lambda s, u="": "DICTATES"  # noqa: E731   # asked only when the text is code-shaped; prose never reaches the judge
    assert all(loop._dictates_code(t, ask=ask) for t in code) and not any(loop._dictates_code(t, ask=ask) for t in prose)


def test_the_authored_reply_is_one_action_or_a_typed_non_action():
    """One imperative per steer; a backticked command ending in a dot is not two sentences (cart-billing-go ternary-bonsai)."""
    ok = "Add it to go.mod via `go get`, and confirm `go build ./...` passes before you change cart.go."
    got = loop._authored_action(ok, Rlog())
    assert got.state.name == "ACCEPTED" and "go build ./..." in got.action and "CODE" not in got.action
    for reply, state in [("Read the file first. Then rewrite the handler.", "STRUCTURAL_REFUSAL"),
                         ("Do these:\n- add the gem\n- run the tests", "STRUCTURAL_REFUSAL"), ("ON_TRACK", "ON_TRACK"),
                         ("", "NO_ACTION"), ("The coder is not ON_TRACK.", "NO_ACTION")]:
        assert loop._authored_action(reply, Rlog()).state.name == state, reply


def test_a_coordinate_the_toolchain_refused_is_not_re_blessed_by_a_later_steer():
    """cart-billing-go 1788241229 / feed-pipeline-java 1788243086: a seat re-blessed `v0.5.0` after the tools refused it."""
    from cria import refusalledger as rl
    tool_out = ("go: github.com/arborize/decimal: remote: Repository not found.\n\tfatal: repository "
                "'https://github.com/arborize/decimal.git/' not found\nImporter.java:[18,29] package com.opencsv.exception does not exist")
    assert {"github.com/arborize/decimal", "com.opencsv.exception"} <= rl.refused_names(tool_out)   # the bare path steers use
    msgs = [{"role": "assistant", "content": "package com.foo does not exist"}, {"role": "tool", "content": tool_out}]
    assert "com.foo" not in rl.scan_messages(msgs) and "com.opencsv.exception" in rl.scan_messages(msgs)   # model words are no refusal
    steer, asked, ledger = "Replace the import with import com.opencsv.exception.CSVParseException;", [], {"com.opencsv.exception"}
    ask = lambda q, u="": asked.append(q) or "PRESCRIBES"  # noqa: E731
    assert loop._prescribes_a_refused_coordinate(steer, ledger, Rlog(), ask) == "com.opencsv.exception"
    assert loop._prescribes_a_refused_coordinate(steer, ledger, Rlog(), None) == ""          # no reasoner: the steer stands
    assert loop._prescribes_a_refused_coordinate("add the correct import", ledger, Rlog(), ask) == "" and len(asked) == 1
