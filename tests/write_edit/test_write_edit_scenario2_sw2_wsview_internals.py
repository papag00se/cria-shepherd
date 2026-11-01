"""wsview second pass: a survey's malformed records (a bad record is no record, never a false fact), the view of a workspace nobody
surveyed, overlapping tool observations that arrive out of order, the session body cache's bounds (files, bytes, sessions), the pending
question queue, and the disk-backed view's missing-path answers. Real survey program over a real tree where one is needed."""
import base64
import contextvars
import hashlib
import os
import subprocess
import zlib

import pytest

from cria import wsview

SESS = "sw2"
OPEN, CLOSE = wsview.SURVEY_OPEN, wsview.SURVEY_CLOSE


def sec(name):
    return f"___CTX_SV_{name}___"


def survey(root, tree, blob=(), entries=None, extra_meta=True):
    rows = [OPEN, sec("meta"), *([f"root\t{root}"] if extra_meta else []), sec("tree"), *tree, sec("blob"), *blob, sec("outside"), sec("progs"),
            sec("done"), f"entries\t{len([t for t in tree if t[:2] in ('D\t', 'F\t', 'X\t')]) if entries is None else entries}", "complete\t1", CLOSE]
    return "\n".join(rows)


@pytest.fixture(autouse=True)
def _clean_caches():
    yield
    for table in (wsview._BODY_MISSES, wsview._PROG_MISSES, wsview._OUTSIDE_MISSES, wsview._BODY_CACHE):
        table.clear()


def b64(text):
    return base64.b64encode(text.encode()).decode()


def test_malformed_records_are_no_record_and_never_a_false_fact():
    tree = ["", "D\t", "D\tsub", "F\t12.5\t4\tgood.txt", "F\tbogus\tnotanumber\tbad.txt", "F\t1\t2\t", "X\t900\tcrowd", "X\t900\t"]
    blob = [f"@{b64('good.txt')}", b64("abcd"), "!A\t7", f"!{b64('too_big.bin')}\tmany", f"!{b64('huge.bin')}\t99999999", "@A", "lines of a body nobody owns",
            f"@{b64('bad.txt')}", "aGk", f"@{b64('empty_owner.txt')}"]
    v = wsview.View("/ws", SESS)
    assert wsview.apply_survey(v, survey("/ws", tree, blob)) and v.surveyed
    assert v.size("good.txt") == 4 and v.read("good.txt") == "abcd" and v.mtime("good.txt") == 12.5
    assert v.size("bad.txt") == 0 and v.isfile("bad.txt") and v.read_bytes("bad.txt") is None and "bad.txt" in v._stale  # unparseable size/body -> unknown
    assert v.undeliverable == ["huge.bin"] and v.isdir("sub") and v.isfile("crowd/anything") is None   # folded dir
    assert not v.complete         # the root itself was folded: nothing may read as absent
    assert v.isfile("never.txt") is None and v.exists("never.txt") is None
    assert wsview.survey_root(survey("", tree, extra_meta=False)) == "" and wsview.apply_survey(wsview.View(None, SESS), survey("", tree, extra_meta=False))


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
    assert v.reroot("sub").isdir("/ws/sub") is True and wsview.apply_survey(wsview.View("/ws", SESS), "garbage") is False


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
    out = subprocess.run(["bash", "-lc", wsview.survey_command(sess, cd=str(root))], capture_output=True, text=True, timeout=60).stdout
    view = wsview.View(str(root), sess)
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])
    return view


def later_request(root, sess):
    out = subprocess.run(["bash", "-lc", wsview.survey_command(sess, cd=str(root))], capture_output=True, text=True, timeout=60).stdout
    view = wsview.View(str(root), sess)
    wsview.apply_survey(view, wsview.strip_survey(out)[1])
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


def packed(text, raw=None, *, n=None, sha=None, wrap=None):
    """The compressed survey transport the harness prints, built independently of the reader: header, one base64(zlib) line, close marker."""
    raw = text.encode() if raw is None else raw
    body = wrap(zlib.compress(raw)) if wrap else base64.b64encode(zlib.compress(raw)).decode()
    return f"{OPEN}\n{wsview.SURVEY_PACKED} {len(text.encode()) if n is None else n} {sha or hashlib.sha256(text.encode()).hexdigest()}\n{body}\n{CLOSE}"


def test_a_packed_survey_is_accepted_only_whole_and_every_corruption_stays_unknown():
    plain = survey("/ws", ["F\t1\t4\tgood.txt"], [f"@{b64('good.txt')}", b64("abcd")])
    text = plain + "\n"
    blobless = survey("/ws", ["F\t1\t4\tgood.txt"], [f"@{b64('good.txt')}", "BLOBLINE"]) + "\n"
    # zero-prefixed record: the raw bytes of a blob body, base64'd back by the reader into the blob line
    head, tail = blobless.split("BLOBLINE\n")
    with_record = head.encode() + b"\x00" + str(len(b"abcd")).encode() + b"\nabcd\n" + tail.encode()
    expected_text = head + base64.b64encode(b"abcd").decode() + "\n" + tail
    v = wsview.View("/ws", SESS)
    assert wsview.apply_survey(v, wsview.strip_survey("before\n" + packed(text) + "\nafter")[1]) and v.read("good.txt") == "abcd"
    v = wsview.View("/ws", SESS)
    assert wsview.apply_survey(v, wsview.strip_survey(packed(expected_text, with_record))[1]) and v.read("good.txt") == "abcd"
    corrupt = [packed(text, sha="0" * 64), packed(text, n=5), packed(text, wrap=lambda z: "!!" + base64.b64encode(z).decode()),
               packed(text, wrap=lambda z: base64.b64encode(z[:-6]).decode()), packed("no open line\n" + text),
               packed(expected_text, with_record.replace(b"\nabcd\n", b"\nabcdX\n", 1)), packed(text, raw=b"\x00zz\n")]
    for block in corrupt:
        v = wsview.View("/ws", SESS)
        assert not wsview.apply_survey(v, wsview.strip_survey(block)[1]) and not v.surveyed
