"""Small owners walked through their public entries: path facts and their confidence (cleanupfacts), request-scoped multipart associations,
the executable-assist selection binding, typed memory effects, and the coder-machine program lookup."""
import pytest

from cria import assistbinding, cleanupfacts as cf, memoryeffects as me, multipartcontext, toolpath, wsview
from cria.assistcontract import Policy

LIT = lambda t: cf.PathFact("literal", t)


@pytest.mark.parametrize("atom,expected", [
    (LIT("/a/b/c.txt"), LIT("/a/b")), (cf.PathFact("path", parent=LIT("/x/y")), LIT("/x")),
    (cf.PathFact("temp-file", parent=cf.PathFact("temp-dir")), cf.PathFact("temp-dir")),
    (cf.PathFact("owned-child", parent=LIT("/w")), LIT("/w")),
    (cf.PathFact("temp-file"), cf.PathFact("temp-parent")), (cf.PathFact("temp-dir"), cf.PathFact("temp-parent")),
    (cf.PathFact("unknown"), cf.PathFact("unknown")), (cf.PathFact("owned-child"), cf.PathFact("unknown")),
])
def test_the_parent_of_a_path_fact_keeps_what_is_known_and_never_invents_a_location(atom, expected):
    assert cf.parent_fact(atom) == expected


@pytest.mark.parametrize("left,right,expected", [
    (LIT("/w"), LIT("a/b"), LIT("/w/a/b")), (LIT("/w"), LIT("/etc"), LIT("/etc")),              # an absolute right side replaces the left
    (cf.PathFact("temp-dir"), LIT("sub"), cf.PathFact("owned-child", parent=cf.PathFact("temp-dir"))),
    (cf.PathFact("owned-child", parent=LIT("/w")), LIT("x/y"), cf.PathFact("owned-child", parent=cf.PathFact("owned-child", parent=LIT("/w")))),
    (cf.PathFact("temp-dir"), LIT("/etc"), LIT("/etc")), (cf.PathFact("owned-child", parent=LIT("/w")), LIT("/etc"), LIT("/etc")),   # MUT2: an absolute right side escapes an owned tree too
    (cf.PathFact("temp-dir"), LIT("../out"), cf.PathFact("unknown")),                              # `..` leaves the owned tree
    (cf.PathFact("unknown"), LIT("x"), cf.PathFact("unknown")), (LIT("/w"), cf.PathFact("unknown"), cf.PathFact("unknown")),
])
def test_joining_path_facts_proves_a_location_only_when_both_sides_are_literal_or_owned(left, right, expected):
    assert cf.join_fact(left, right) == expected


@pytest.mark.parametrize("atom,root", [(LIT("/"), True), (LIT("//"), True), (LIT("/./"), True), (LIT("/a"), False), (cf.PathFact("path", parent=LIT("/")), True),
                                       (cf.PathFact("unknown"), False), (None, False)])
def test_only_a_literal_that_normalises_to_slash_is_the_root(atom, root):
    assert cf.is_root(atom) is root


@pytest.mark.parametrize("permission", ["read", "write"])
def test_deleting_double_slash_recursively_is_the_root_delete_at_every_permission(permission):
    """`shutil.rmtree("//")` deletes `/` on Linux. normpath keeps `//` as is, so it used to fall through to a workspace-relative `within` verdict
    at write level (not blocked) and a mislabelled `external` at read level; it is the root rule, like `/` and `///`."""
    from cria import cleanupsafety
    for target in ("/", "//", "///"):
        got = cleanupsafety.analyze("x.py", f'import shutil\nshutil.rmtree("{target}")\n', "/w", permission)
        assert [(f.confidence, f.rule) for f in got.findings] == [("PROVEN", "root")] and got.blocked, target


@pytest.mark.parametrize("targets,workspace,permission,recursive,possible,expected", [
    ([LIT("/")], "/w", "read", True, False, ("PROVEN", "root")),
    ([LIT("/")], "/w", "read", False, False, ("PROVEN", "external")),                            # not recursive: just an external path
    ([LIT("/")], "/w", "write", True, False, ("PROVEN", "root")),
    ([LIT("/etc/x")], "/w", "write", False, False, ("WITHIN_SCOPE", "within")),                  # write level: external is the operator's choice
    ([LIT("/etc/x")], "/w", "read", False, False, ("PROVEN", "external")),
    ([LIT("/w/a")], "/w", "read", False, False, ("WITHIN_SCOPE", "within")),
    ([LIT("/w/a")], None, "read", False, False, ("UNKNOWN", "unresolved")),                      # no workspace: cannot call it within
    ([cf.PathFact("temp-parent")], "/w", "read", True, False, ("PROVEN", "temp_parent")),
    ([cf.PathFact("temp-parent")], "/w", "read", False, False, ("UNKNOWN", "unresolved")),
    ([cf.PathFact("temp-file"), cf.PathFact("owned-child")], "/w", "read", False, False, ("WITHIN_SCOPE", "within")),
    ([LIT("/etc/x"), cf.PathFact("unknown")], "/w", "read", False, False, ("POSSIBLE", "external")),
    ([LIT("/etc/x")], "/w", "read", False, True, ("POSSIBLE", "external")),
    ([cf.PathFact("path", parent=LIT("/etc"))], "/w", "read", False, False, ("PROVEN", "external")),
    ([], "/w", "read", False, False, ("UNKNOWN", "unresolved")),
    ([cf.PathFact("unknown")], "/w", "read", False, False, ("UNKNOWN", "unresolved")),
    ([LIT("/"), LIT("/etc")], "/w", "read", True, False, ("PROVEN", "root")),                    # the worst rule names the finding
])
def test_confidence_is_proven_only_when_every_target_is_unsafe_and_nothing_is_uncertain(targets, workspace, permission, recursive, possible, expected):
    assert cf.classify(targets, workspace, permission, recursive, possible) == expected


def test_an_analysis_blocks_on_a_proven_finding_or_an_uncertain_root_only():
    finding = lambda conf, rule: cf.Finding(conf, rule, 1, "rm")
    blocked = lambda *fs: cf.Analysis("sh", tuple(fs), "supported-subset").blocked
    assert blocked(finding("PROVEN", "external")) and blocked(finding("POSSIBLE", "root_uncertain"))
    assert not blocked(finding("POSSIBLE", "external"), finding("UNKNOWN", "unresolved"), finding("WITHIN_SCOPE", "within")) and not blocked()


def test_multipart_associations_exist_only_inside_a_bound_request_and_are_taken_once():
    """Outside `bound()` nothing is recorded or returned; inside, an alias is taken once and only by the SAME call object (a lookalike dict
    is not it) and leaves it in place; prefixes are kept per call id; a nested request does not leak into the outer one after it ends."""
    call, twin = {"id": "c"}, {"id": "c"}
    multipartcontext.record(call, {"x": 1})
    multipartcontext.record_prefix("c", "t", "p")
    assert multipartcontext.take(call) is None and multipartcontext.prefix("c") is None
    with multipartcontext.bound():
        multipartcontext.record(call, {"x": 1})
        multipartcontext.record_prefix("c", "text", "pre")
        assert multipartcontext.take(twin) is None                      # equal but not identical: not the association
        assert multipartcontext.take(call) == {"x": 1} and multipartcontext.take(call) is None
        assert multipartcontext.prefix("c") == ("text", "pre") and multipartcontext.prefix("other") is None
        with multipartcontext.bound():
            assert multipartcontext.prefix("c") is None
        assert multipartcontext.prefix("c") == ("text", "pre")
    assert multipartcontext.prefix("c") is None


class Def:
    def __init__(self, ident):
        self.policy, self.execute = Policy(ident, "returned", 1), None


class Sub(Def):
    pass


class Selection:
    engagement_level = 0

    def __init__(self, *definitions):
        self.definitions = definitions


def test_a_selection_binds_only_inside_its_scope_and_an_absent_or_ambiguous_member_is_never_defaulted():
    """Unbound: the standalone definition is used and nothing is bound. Bound: the exact member of the standalone's type, None when absent,
    TypeError for a duplicate or an incompatible type; UNBOUND itself can never be bound; leaving the scope restores the previous binding."""
    standalone = Def("a")
    assert assistbinding.current() is assistbinding.UNBOUND and not assistbinding.is_bound() and assistbinding.selected_definition(standalone) is standalone
    member, other = Def("a"), Def("b")
    with assistbinding.bound(Selection(member, other)) as sel:
        assert assistbinding.is_bound() and assistbinding.current() is sel and assistbinding.selected_definition(standalone) is member
        assert assistbinding.selected_definition(Def("zzz")) is None
        with assistbinding.bound(Selection()):
            assert assistbinding.selected_definition(standalone) is None
        assert assistbinding.current() is sel
    with assistbinding.bound(Selection(member, Def("a"))), pytest.raises(TypeError, match="one compatible definition: a"):
        assistbinding.selected_definition(standalone)
    with assistbinding.bound(Selection(Def("a"))), pytest.raises(TypeError):
        assistbinding.selected_definition(Sub("a"))
    with pytest.raises(ValueError, match="absence"), assistbinding.bound(assistbinding.UNBOUND):
        pass
    assert assistbinding.current() is assistbinding.UNBOUND


def test_a_memory_effect_rejects_a_foreign_effect_a_negative_count_and_a_no_op_that_claims_change():
    assert me.MessageEffect([]).effect is me.Effect.NO_OP and me.MessageEffect([{"role": "user"}], me.Effect.REDUCED, 2).count == 2
    for bad, message in ((dict(effect="reduced"), "Invalid memory effect"), (dict(effect=me.Effect.REDUCED, count=-1), "Invalid memory effect"),
                         (dict(effect=me.Effect.NO_OP, count=1), "No-op cannot report changed items")):
        with pytest.raises(ValueError, match=message):
            me.MessageEffect([], **bad)
    assert [e.value for e in me.Effect] == ["no-op", "withheld", "reduced", "pending", "delivered", "settled"]


def test_the_coder_machines_program_lookup_has_three_states_and_an_empty_name_is_never_asked(monkeypatch):
    """Empty name: "" without asking. Otherwise exactly what the coder's view says: a resolved name, "" for resolves-nothing, None for not asked yet."""
    asked = []

    class View:
        def program(self, name):
            asked.append(name)
            return {"ruby": "ruby", "bundle": "bundle3.2", "nope": ""}.get(name)
    monkeypatch.setattr(wsview, "current", lambda *a, **k: View())
    assert toolpath.resolved("") == "" and asked == []
    assert [toolpath.resolved(n) for n in ("ruby", "bundle", "nope", "never-asked")] == ["ruby", "bundle3.2", "", None]
