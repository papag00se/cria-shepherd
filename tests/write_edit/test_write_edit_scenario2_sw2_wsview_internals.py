"""wsview second pass: a survey's facts are three-valued (an unlisted or folded path is unknown, never absent), the view of a workspace
nobody surveyed, overlapping tool observations that arrive out of order, the session body cache's bounds (files, bytes, sessions), the
pending question queue, and the disk-backed view's missing-path answers. The real survey operation over a real tree where one is needed."""
import contextvars
import os

import pytest
from survey_fixtures import survey_of_disk, typed

from cria import wsview

SESS = "sw2"


def survey(root, tree, blobs=None, **kw):
    return typed(root, tree, blobs=blobs, **kw)


@pytest.fixture(autouse=True)
def _clean_caches():
    yield
    for table in (wsview._BODY_MISSES, wsview._PROG_MISSES, wsview._OUTSIDE_MISSES, wsview._BODY_CACHE):
        table.clear()


def test_a_surveys_facts_are_three_valued_and_what_it_could_not_hand_back_is_said():
    tree = ["D\tsub", "F\t12\t4\tgood.txt", "F\t0\t0\tbad.txt", "X\t900\tcrowd", "X\t900\t"]
    v = wsview.View("/ws", SESS)
    assert wsview.apply_survey(v, survey("/ws", tree, {"good.txt": b"abcd"}, refused={"huge.bin": 99_999_999, "gone.txt": wsview.ABSENT}))
    assert v.surveyed
    assert v.size("good.txt") == 4 and v.read("good.txt") == "abcd" and v.mtime("good.txt") == 12.0
    assert v.size("bad.txt") == 0 and v.isfile("bad.txt") and v.read_bytes("bad.txt") is None        # no body was delivered: unknown
    assert v.undeliverable == ["gone.txt", "huge.bin"] and v.isdir("sub") and v.isfile("crowd/anything") is None   # folded dir
    assert not v.complete         # the root itself was folded: nothing may read as absent
    assert v.isfile("never.txt") is None and v.exists("never.txt") is None
    assert not wsview.apply_survey(wsview.View("/other", SESS), survey("/ws", tree)) and wsview.last_reject()["reason"] == "different-tree"
    rootless = wsview.View(None, SESS)
    assert wsview.apply_survey(rootless, survey("/ws", tree)) and rootless.root == "/ws"
    assert not wsview.apply_survey(wsview.View("/ws", SESS), survey("/ws", [], listed=False)) and wsview.last_reject()["reason"] == "no-tree"


def test_a_view_nobody_surveyed_answers_unknown_not_absent():
    v = wsview.View("/ws", SESS)
    assert (v.isdir("a"), v.isdir("/ws"), v.isfile("a"), v.mtime("a"), v.walk("."), v.files(), v.read_current_survey("a")) == (None,) * 7
    rootless = wsview.View(None, SESS)
    assert (rootless.rel("/x"), rootless.isdir("/x"), rootless.isfile("/x"), rootless.rel("")) == (None, None, None, None)
    assert v.outside_kind("") is None and v.program("") is None
    assert v.outside_kind("/never/asked") is None and v.program("never-asked") is None
    assert wsview.pending(SESS) == ([], ["never-asked"], ["/never/asked"])   # asking IS the request for the next survey
    assert wsview.apply_survey(v, survey("/ws", ["D\tsub", "F\t5\t3\tsub/a.txt"])) and v.isdir("/ws") and v.isfile("sub") is False and v.isfile("sub/a.txt")
    assert v.walk("sub/missing") is None and v.isdir("/else/x") is None and v.isfile("/else/x") is None and v.mtime("sub/missing") is None
    assert v.reroot("sub").isdir("/ws/sub") is True


def test_overlapping_observations_arriving_out_of_order_never_overwrite_the_later_bytes():
    fo = wsview.from_observation

    def held():
        v = wsview.View("/ws", SESS)
        return v, v.begin_observation(), v.begin_observation()    # first-started, later-started
    v, first, later = held()
    fo(later, v.note_written, "/ws/a.py", "new\n")
    fo(first, v.note_written, "/ws/a.py", "new\n")                # the overtaken report AGREES: nothing to doubt
    assert v.read("a.py") == "new\n" and v.observation_current(first)
    v, first, later = held()
    fo(later, v.note_written, "/ws/a.py", "new\n")
    fo(first, v.note_written, "/ws/a.py", "old\n")                # it DISAGREES and nobody can order them: authority withheld, history kept
    assert v.read("a.py") is None and not v.complete and v.read_observed_bytes("/ws/a.py") == b"new\n" and v._observed_bodies["a.py"] == b"new\n"
    v, first, later = held()
    fo(later, v.note_written, "/ws/a.py", "new\n")
    assert not fo(first, v.note_edited, "/ws/a.py", "new", "x") and fo(first, v.note_changed, "/ws/a.py") is None
    assert v.read("a.py") == "new\n"                              # an overtaken edit/change report cannot disturb a later body
    third = v.begin_observation()
    assert fo(third, v.note_edited, "/ws/a.py", "new", "x2") and v.read("a.py") == "x2\n"
    v.observation_pending(True)                                   # open effects: nothing observed under them is current authority
    pending = v.begin_observation()
    assert not v.observation_current(pending) and not fo(pending, v.note_edited, "/ws/a.py", "x2", "x3") and v.read("a.py") is None
    assert v.settle_observation(pending, current=False).uncertain and not v.observation_current(wsview.Observation(object(), 1, 0, 0))
    v.note_written("/ws/b.py", "b\n")                             # no observation bound, effects open: recorded but not authority
    assert v.read("b.py") is None
    assert not wsview.apply_survey(v, survey("/ws", ["F\t1\t2\tb.py"])) and wsview.last_reject()["reason"] == "unresolved-observation"
    stale = wsview.View("/ws", SESS)
    assert not fo(first, wsview.apply_survey, stale, survey("/ws", [])) and wsview.last_reject()["reason"] == "overtaken-observation"


@pytest.fixture
def real(tmp_path):
    for i in range(70):
        (tmp_path / f"f{i}.txt").write_text(f"x{i}\n")
    for n in range(3):
        (tmp_path / f"m{n}.bin").write_bytes(b"y" * 1_200_000)
    return tmp_path


def surveyed(root, sess):
    view = wsview.View(str(root), sess)
    assert wsview.apply_survey(view, survey_of_disk(root, session=sess))
    return view


def later_request(root, sess):
    view = wsview.View(str(root), sess)
    wsview.apply_survey(view, survey_of_disk(root, session=sess))
    return view


def test_the_session_body_cache_keeps_the_newest_64_files_and_2mb_per_workspace(real):
    a = surveyed(real, "files")
    for i in range(70):
        a.note_written(str(real / f"f{i}.txt"), f"x{i}\n")
    later = later_request(real, "files")
    assert [i for i in range(70) if later.read(f"f{i}.txt")] == list(range(6, 70))        # the 6 oldest were evicted
    b = surveyed(real, "bytes")
    for n in range(3):
        b.note_written(str(real / f"m{n}.bin"), "y" * 1_200_000)
    later = later_request(real, "bytes")
    assert [n for n in range(3) if later.read_bytes(f"m{n}.bin")] == [2]                 # 2 x 1.2 MB exceeds the bound: only the newest stays


def test_the_cache_and_the_question_queue_forget_whole_sessions_past_512_but_keep_the_newest(tmp_path):
    for k in range(515):
        wsview.View(str(tmp_path), f"s{k}").note_written(str(tmp_path / "a"), "a")
        wsview.want_body(f"s{k}", f"p{k}")
    assert (str(tmp_path) in {r for _s, r in wsview._BODY_CACHE}) and ("s0", str(tmp_path)) not in wsview._BODY_CACHE and ("s514", str(tmp_path)) in wsview._BODY_CACHE
    assert wsview.pending("s0") == ([], [], []) and wsview.pending("s514")[0] == ["p514"]
    for i in range(80):
        wsview.want_body("long", f"f{i}")
    wsview.want_body("long", "f79")                                                      # a repeated question is not queued twice
    wsview.want_body("", "x")
    wsview.want_body("long", "")
    queue = wsview.pending("long")[0]
    assert len(queue) == 64 and queue[0] == "f16" and queue[-1] == "f79"
    wsview.clear_pending("long", ["f79", "f16"], [], [])
    assert "f79" not in wsview.pending("long")[0] and len(wsview.pending("long")[0]) == 62


def test_the_disk_view_answers_absent_paths_as_unknown_and_finds_versioned_programs(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "pyx3.12"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    (bindir / "pyxnoexec1.0").write_text("x")
    monkeypatch.setenv("PATH", f"{tmp_path / 'nonexistent'}{os.pathsep}{bindir}")
    d = wsview.DirectView(str(tmp_path))
    gone = str(tmp_path / "gone")
    assert (d.mtime(gone), d.read_bytes(gone), d.listdir(gone), d.scandir(gone), d.walk(gone), d.files(), d.program("")) == (None,) * 7
    assert d.program("pyx") == "pyx3.12" and d.program("pyxnoexec") == "" and d.program("zz-nothing") == ""
    assert d.read_observed_bytes(str(tool)) == b"#!/bin/sh\n" and d.mtime(str(tool)) > 0 and d.outside_kind(str(bindir)) == "d" and d.outside_kind(gone) == ""
    ambient = wsview.current().root
    token = wsview.bind(d)
    assert wsview.current().root == d.root
    wsview.unbind(token)
    assert wsview.current().root == ambient
    token = wsview.bind(d)
    contextvars.copy_context().run(wsview.unbind, token)      # a token set in another context is simply ignored
    assert wsview.current().root == d.root
    wsview.unbind(token)
    assert wsview.current("/x").isfile("/x") is None


def test_the_survey_answers_programs_versioned_names_and_outside_paths_from_the_coders_own_shell(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, mode in (("pyx3.12", 0o755), ("pyxnoexec1.0", 0o644), ("tool", 0o755), ("tool2.7", 0o755)):
        (bindir / name).write_text("#!/bin/sh\n")
        (bindir / name).chmod(mode)
    ws = tmp_path / "ws"
    ws.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    (tmp_path / "afile").write_text("x")
    found = survey_of_disk(ws, progs=["pyx", "pyxnoexec", "zz-nothing", "tool", "sh; echo no"], outside=[str(cache), str(tmp_path / "afile"), str(tmp_path / "gone"), "~"],
                           env={"PATH": f"{tmp_path / 'nonexistent'}:{bindir}:/usr/bin:/bin"})
    assert found.progs == {"pyx": "pyx3.12", "pyxnoexec": "", "zz-nothing": "", "tool": "tool", "sh; echo no": ""}     # the name is data, never run
    assert found.outside == {str(cache): "d", str(tmp_path / "afile"): "f", str(tmp_path / "gone"): "", "~": "d"}


def test_the_survey_hands_back_what_it_can_and_says_what_it_cannot(tmp_path):
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "small.txt").write_text("abcd")
    (ws / "big.txt").write_bytes(b"x" * (wsview.BLOB_FILE_MAX + 1))
    (ws / "mid.bin").write_bytes(bytes(range(256)) * 100)          # 25,600 bytes: more than one page, not valid text
    found = survey_of_disk(ws, bodies=["small.txt", "big.txt", "gone.txt", "sub", "mid.bin", "sub/x/y"])
    assert found.bodies == {"small.txt": b"abcd", "mid.bin": bytes(range(256)) * 100}
    assert found.refused == {"big.txt": wsview.BLOB_FILE_MAX + 1, "gone.txt": wsview.ABSENT, "sub": wsview.UNSTATABLE, "sub/x/y": wsview.ABSENT}
