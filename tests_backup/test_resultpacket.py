"""The record codec: lossless, verified, and strict about what a record may be."""
import base64
import hashlib
import json
import os

import pytest

from cria import resultpacket as rp

R = "0123456789abcdef"


@pytest.mark.parametrize("raw", [b"", b"plain\n", b"caf\xc3\xa9 \r\n tail", bytes(range(256)), b"\x00\x01\xff" * 700, os.urandom(4000),
                                 b"x" * 100_000])
def test_every_body_round_trips_exactly_whatever_codec_wins(raw):
    line = rp.line(R, rp.RAN, body=raw, observe=rp.WHOLE)
    assert line.endswith("\n") and line.count("\n") == 1 and line.isascii()           # one ASCII line, no raw LF inside
    rec = rp.read_record(line, 0, R)
    assert rec is not None and rec.body == raw and rec.observe == rp.WHOLE and rec.end == len(line)


def test_the_codec_is_chosen_by_serialized_length_with_a_fixed_tiebreak():
    text = b"def f():\n    return 1\n" * 200
    body = json.loads(rp.line(R, rp.RAN, body=text))["b"]
    assert body["c"] == "z"                                                           # compressible: zlib wins
    assert json.loads(rp.line(R, rp.RAN, body=b"ab"))["b"]["c"] == "j"                  # tiny text stays text
    assert json.loads(rp.line(R, rp.RAN, body=b"\xff\xfe\xfd"))["b"]["c"] == "b"       # not UTF-8: text is impossible


def test_a_crlf_terminator_is_accepted_and_changes_no_other_byte():
    line = rp.line(R, rp.REFUSED, pre="⟦ctx:denied⟧ x\n", body=b"a\r\nb")
    rec = rp.read_record(line.replace("\n", "\r\n"), 0, R)
    assert rec is not None and rec.body == b"a\r\nb" and rec.pre == "⟦ctx:denied⟧ x\n"


@pytest.mark.parametrize("mutate", [
    lambda d: {**d, "r": "ffffffffffffffff"},                       # another call's receipt
    lambda d: {**d, "v": 2},                                        # another version
    lambda d: {**d, "k": "survey"},                                 # a survey where record 1 belongs
    lambda d: {**d, "k": "bogus"},
    lambda d: {**d, "o": "partial"},                                # an observation this protocol does not define
    lambda d: {k: v for k, v in d.items() if k != "b"},             # a whole-read observation with no body
    lambda d: {**d, "b": {**d["b"], "n": d["b"]["n"] + 1}},         # length does not verify
    lambda d: {**d, "b": {**d["b"], "h": "0" * 64}},                # digest does not verify
    lambda d: {**d, "b": {**d["b"], "c": "q"}},                     # unknown codec
    lambda d: {**d, "b": {**d["b"], "extra": 1}},                   # unknown field
])
def test_a_malformed_or_foreign_first_record_is_not_a_record(mutate):
    d = json.loads(rp.line(R, rp.RAN, body=b"abc", observe=rp.WHOLE))
    assert rp.read_record(json.dumps(mutate(d), separators=(",", ":")) + "\n", 0, R) is None


def test_a_record_is_read_only_at_the_position_it_is_asked_for_and_never_searched_for():
    line = rp.line(R, rp.REFUSED)
    assert rp.read_record("x" + line, 0, R) is None and rp.read_record("\n" + line, 0, R) is None
    assert rp.read_record(line, 0, R[::-1]) is None and rp.read_record(line[:-1], 0, R) is None   # unterminated
    assert rp.read_record(line + line, len(line), R) is not None                                    # the second one, by position


def test_a_survey_record_is_valid_only_where_a_survey_is_asked_for():
    s = rp.line(R, rp.SURVEY, body=b"block")
    assert rp.read_record(s, 0, R, survey=True).body == b"block" and rp.read_record(s, 0, R) is None
    assert rp.read_record(rp.line(R, rp.RAN), 0, R, survey=True) is None


def test_a_range_observation_and_the_typed_reports_are_validated_fields():
    window = rp.line(R, rp.RAN, body=b"3: c\n", observe=rp.RANGE)
    assert rp.read_record(window, 0, R).observe == rp.RANGE
    ok = rp.line(R, rp.LANDED, rep={"ev": "e30=", "late": True, "rm": "removed 2", "st": {
        "operation": "o", "target": "t", "byte_count": 3, "sha256": "h"}})
    assert rp.read_record(ok, 0, R).rep["ev"] == "e30="
    for bad in ({"ev": 1}, {"late": False}, {"nope": "x"}, {"st": {"operation": "o"}}, {"st": {"operation": "o", "target": "t",
                "byte_count": True, "sha256": "h"}}, {}, [], "x"):
        assert rp.read_record(rp.line(R, rp.LANDED, rep=bad) if bad else '{"v":1,"r":"%s","k":"landed","rep":%s}\n' % (R, json.dumps(bad)),
                              0, R) is None


def test_the_wire_cost_of_a_record_is_a_true_upper_bound_and_the_budget_inverts_it():
    for n in (0, 1, 999, 5000, 9000):
        data = os.urandom(n)                         # incompressible: the worst case the codec can face
        assert len(rp.line(R, rp.SURVEY, body=data)) <= rp.wire_cost(n)
    for wire in (500, 1000, 5000, 6900):
        n = rp.max_text_for_wire(wire)
        assert rp.wire_cost(n) <= wire and (n == 0 or rp.wire_cost(n + 3) > wire)


def _first_record_variants(raw_body=b"verified original\n"):
    """The malformed shapes an independent review executed against a real first record: each declares the same body, length and
    digest, and is accepted by a lenient decoder."""
    import zlib
    good = json.loads(rp.line(R, rp.RAN, body=raw_body, observe=rp.WHOLE))
    text = json.dumps(good, separators=(",", ":"))
    trailing = {**good, "b": {**good["b"], "c": "z", "d": base64.b64encode(zlib.compress(raw_body) + b"TRAILING DATA").decode()}}
    return {
        "boolean-version": text.replace('"v":1', '"v":true', 1),
        "float-version": text.replace('"v":1', '"v":1.0', 1),
        "duplicate-kind": text.replace('"k":"ran"', '"k":"refused","k":"ran"', 1),
        "duplicate-body-key": text.replace('"n":18', '"n":18,"n":18', 1),
        "zlib-trailing-data": json.dumps(trailing, separators=(",", ":")),
    }


@pytest.mark.parametrize("shape", ["boolean-version", "float-version", "duplicate-kind", "duplicate-body-key", "zlib-trailing-data"])
def test_a_malformed_record_is_not_a_record_and_the_valid_original_still_is(shape):
    variants = _first_record_variants()
    assert rp.read_record(variants[shape] + "\n", 0, R) is None
    assert rp.read_record(rp.line(R, rp.RAN, body=b"verified original\n", observe=rp.WHOLE), 0, R) is not None


def test_a_report_declared_twice_is_not_a_record():
    text = rp.line(R, rp.LANDED, rep={"ev": "a"}).replace('"ev":"a"', '"ev":"a","ev":"b"', 1)
    assert rp.read_record(text, 0, R) is None
