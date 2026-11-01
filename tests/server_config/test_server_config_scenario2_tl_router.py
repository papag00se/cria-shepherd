"""Router resolution over every backend shape: the failover chain per task type (question falls back to the reasoning then the coding chain), what each role resolves to
(served / keyed / cli), what is skipped and logged, and which endpoint the loop's own internal calls get. Only the provider constructors are fakes."""
import os

import pytest

from cria.config import Backend, Role, RoutingConfig
from cria.routing import Router


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def decide(self, kind, role, why, **kw):
        self.events.append((kind, role, why, kw))


class Served:
    def __init__(self, name):
        self.name = name

    def loaded_model(self, rlog):
        return f"model-of-{self.name}"


def make(tmp_path, monkeypatch, **cfg):
    made = []

    def provider(base, key):
        made.append((base, key))
        return Served(base)

    cli = tmp_path / "fakeclaude"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    plain = tmp_path / "notexec"
    plain.write_text("x")
    monkeypatch.setenv("TL_KEY", "sekret\r\n")
    monkeypatch.delenv("TL_NOKEY", raising=False)
    backends = {"local": Backend("local"), "own": Backend("own", base_url="http://own:1"), "same": Backend("same", base_url="http://shared:0"),
                "keyed": Backend("keyed", base_url="http://remote", api_key_env="TL_KEY", model="gpt-x"),
                "nokey": Backend("nokey", base_url="http://remote", api_key_env="TL_NOKEY"),
                "cli": Backend("cli", transport="cli", binary=str(cli), cwd="/w"), "nocli": Backend("nocli", transport="cli", binary=str(plain)),
                "which": Backend("which", transport="cli", binary="sh")}
    roles = {n: Role(n, n) for n in backends} | {"ghost": Role("ghost", "missing")}
    rc = RoutingConfig(backends=backends, roles=roles, defaults_base_url="http://shared:0", **cfg)
    shared = Served("shared")
    return Router(rc, shared, provider_factory=provider, claude_factory=lambda b: ("cli", b.binary)), shared, made


def test_the_first_resolvable_role_wins_and_every_skip_and_exhaustion_is_logged(tmp_path, monkeypatch):
    r, shared, made = make(tmp_path, monkeypatch, failover={"coding": ("ghost", "nokey", "nocli", "own", "keyed"), "reasoning": ("keyed",), "dead": ("ghost", "nokey")})
    log = Log()
    route = r.route("coding", log)
    assert (route.role, route.model, route.reason) == ("own", "model-of-http://own:1", "chain[coding] -> own")
    assert [e[0] for e in log.events] == ["route.skip", "routing.backend_skipped", "route.skip", "route.skip", "route"]
    assert log.events[1][1]["missing"] == "TL_NOKEY" and log.events[2][1]["role"] == "nokey"
    assert r.route("question", Log()).role == "keyed"                       # question -> reasoning chain
    assert r.route("question", Log()).provider is r.route("question", Log()).provider and made.count(("http://remote", "sekret")) == 1   # CRLF-safe key, cached
    log = Log()
    assert r.route("dead", log) is None and log.events[-1][0] == "route.exhausted" and log.events[-1][1]["chain"] == ["ghost", "nokey"]
    r2, _, _ = make(tmp_path, monkeypatch, failover={"coding": ("which",)})
    assert r2.route("question", Log()).role == "which" and r2.route("anything", Log()).provider == ("cli", "sh")   # question falls to coding; a bare binary is found on PATH
    r3, _, _ = make(tmp_path, monkeypatch)
    assert r3.route("coding", Log()) is None                                 # no routing config -> passthrough


def test_a_route_carries_the_resolvable_links_in_order_and_cli_resolution_checks_the_file(tmp_path, monkeypatch):
    r, _, _ = make(tmp_path, monkeypatch, failover={"coding": ("cli", "nocli", "ghost", "same", "keyed")})
    log = Log()
    chain = r.route("coding", log).provider.hops
    rl = Log()
    assert [(h.role, h.model(rl)) for h in chain] == [("cli", None), ("same", "model-of-shared"), ("keyed", "gpt-x")]
    assert chain[0].provider == ("cli", chain[0].provider[1]) and os.path.basename(chain[0].provider[1]) == "fakeclaude"
    assert [e[1]["role"] for e in log.events if e[0] == "route.skip"] == ["nocli", "ghost"]
    r2, _, _ = make(tmp_path, monkeypatch)
    assert r2.route("coding", Log()) is None


@pytest.mark.parametrize("role,expected", [
    ("missing-role", "shared"),      # unknown role -> the shared endpoint
    ("ghost", "shared"),             # role bound to an undefined backend
    ("cli", "shared"),               # a cli backend is not a chat endpoint
    ("local", "shared"),             # served, no base_url
    ("same", "shared"),              # served on the shared url
    ("nokey", "shared"),             # keyed, key absent
    ("own", "http://own:1"),         # served on its own endpoint
    ("keyed", "http://remote"),      # keyed and authed
])
def test_loop_internal_calls_get_the_endpoint_their_role_can_reach(tmp_path, monkeypatch, role, expected):
    r, shared, _ = make(tmp_path, monkeypatch)
    ep = r.endpoint_for(role)
    assert (ep is shared) if expected == "shared" else ep.name == expected
