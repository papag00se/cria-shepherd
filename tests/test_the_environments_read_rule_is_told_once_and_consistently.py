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
    assert "every file you read or write" not in refusal and "installed-library" not in refusal
    assert "Writes must stay inside" in refusal


def test_a_superseded_note_does_not_invite_a_reread():
    note = prompts.render("superseded_writes_dropped", count="1", paths="Importer.java")
    assert "remains above in full" in note and "Nothing was lost" in note
    # not knowable: a later edit_file/sed -i/formatter can change the disk; main's re-read sentence stays
    assert "what is on disk" not in note and "already in this conversation" not in note
    assert "To be sure, read the file" in note


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


def test_the_note_never_starts_with_a_design_comment_line():
    note = dirguard.readable_roots_note(_msgs(), RUNS)
    assert note and not note.lstrip().startswith("#")


def test_assistant_text_is_never_the_source_of_the_build_location():
    guess = "-Dmaven.repo.local=%s/guess" % INSTALL
    msgs = _msgs("no build output yet") + [{"role": "assistant", "content": "I will run mvn " + guess}]
    note = dirguard.readable_roots_note(msgs, RUNS)
    assert "/guess" not in note and INSTALL in note


def test_every_command_the_note_names_is_allowed_on_a_declared_root():
    roots = dirguard.declared_roots(_msgs())
    for c in (f"ls {INSTALL}/m2/repository", f"find {INSTALL}/m2/repository -name '*.jar'",
              f"cat {INSTALL}/m2/repository/a.pom", f"grep -r opencsv {INSTALL}/m2/repository",
              f"unzip -l {INSTALL}/m2/repository/o.jar", f"jar tf {INSTALL}/m2/repository/o.jar",
              f"javap -cp {INSTALL}/m2/repository/o.jar com.opencsv.CSVReader"):
        assert dirguard.command_refusal(c, "none", RUNS, roots) is None, c


def test_the_refusal_claims_reads_only_where_reads_are_refused():
    r = dirguard.path_refusal("/etc/x/y", True, "none", RUNS)
    assert r and "dependency-artifact folders" in r and "installed-library" not in r
    w = dirguard.path_refusal("/etc/x/y", True, "read", RUNS)
    assert w and "READS" not in w and "Writes must stay inside" in w
    assert dirguard.path_refusal("/usr/share/java/x.jar", False, "none", RUNS) is not None
