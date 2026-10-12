"""O2 + O3 (ornith1.5_9b / feed-pipeline-java B1, session 20261011T232005-01a12ec4).

O2: cria ALLOWED read-only commands on the harness-declared roots (the cell's Maven repository) but its
own prompt told the model every file it reads/writes stays inside the project and that exec_command is
not for reading — so the coder never opened the OpenCSV jar and invented the API.
O3: three notes ("To be sure, read the file", "trust THIS list plus read_file", "read_file is the only
current answer") invited re-reading text already present, against coder_system's "use that result".
"""
from cria import contextfloor, dirguard, focustrim, groundtruth, loop, prompts

INSTALL = "/home/jesse/.cria/suite-installs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791785998-32orkgte"
RUNS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791785998-32orkgte"
PERM = ("<permissions instructions>\nThe sandbox permits reading files, and editing files in `cwd` and "
        "`writable_roots`.\n The writable roots are `%s`, `%s`.\n</permissions instructions>" % (INSTALL, RUNS))
JTO = ('Picked up JAVA_TOOL_OPTIONS: "-Dmaven.repo.local=%s/m2/repository" "-Djava.io.tmpdir=%s/java-tmp"'
       % (INSTALL, INSTALL))


def _msgs(tool_text=JTO):
    return [{"role": "system", "content": PERM},
            {"role": "user", "content": "build the importer"},
            {"role": "tool", "tool_call_id": "c1", "content": tool_text}]


def test_the_fact_names_the_readable_roots_and_the_builds_dependency_cache():
    note = dirguard.readable_roots_note(_msgs(), RUNS)
    assert INSTALL in note and INSTALL + "/m2/repository" in note
    assert RUNS not in note.replace(INSTALL, "")            # the project itself is not an "outside" root
    assert "javap" in note and "read_file" in note


def test_no_declared_roots_or_unproven_cache_adds_nothing():
    assert dirguard.readable_roots_note([{"role": "user", "content": "hi"}], RUNS) == ""
    other = _msgs('"-Dmaven.repo.local=/home/jesse/elsewhere/m2"')
    note = dirguard.readable_roots_note(other, RUNS)
    assert "/elsewhere/" not in note and INSTALL in note     # only a location the guard allows is claimed


def test_the_coder_frame_carries_the_fact_only_when_roots_are_declared():
    msgs = _msgs()
    framed = loop._frame_for_item(msgs, "t", "", 0, 1, synthetic=True, workspace_root=RUNS)
    assert INSTALL + "/m2/repository" in framed[0]["content"]
    plain = loop._frame_for_item([{"role": "user", "content": "x"}], "t", "", 0, 1, synthetic=True)
    assert "READ these directories" not in plain[0]["content"]


def test_the_rules_the_model_reads_no_longer_forbid_what_is_allowed():
    sys_txt = prompts.load("coder_system")
    assert "EVERYTHING inside" not in sys_txt and "READING installed libraries" in sys_txt
    assert "archive" in prompts.load("cheatsheet")
    refusal = prompts.load("external_path_refusal")
    assert "every file you read or write" not in refusal and "only READS" in refusal
    assert "Writes must stay inside" in refusal


def test_a_superseded_note_does_not_invite_a_reread():
    note = prompts.render("superseded_writes_dropped", count="1", paths="Importer.java")
    assert "read the file" not in note and "Nothing was lost" in note and "still here in full" in note


def test_the_inventory_directs_reading_only_files_whose_text_is_not_here():
    labels = prompts.load_map("workspace_inventory")
    for k in ("coder_header", "coder_note"):
        assert "trust THIS list plus read_file" not in labels[k] and "only current version" not in labels[k]
    assert "not in this conversation" in labels["coder_note"] and "use that copy" in labels["coder_note"]


def test_the_compaction_note_points_at_a_later_copy_before_a_re_read():
    dropped = [{"role": "tool", "tool_call_id": "c1",
                "content": "<html><body>" + "<div class='x'>hello world</div>" * 200 + "</body></html>"}]
    note = contextfloor._compacted_note(dropped, 1, 20000)["content"]
    assert "what the file said THEN" in note and "only current answer" not in note
    assert "later copy" in note
