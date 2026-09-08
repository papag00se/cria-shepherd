"""A weak model must be able to READ an installed dependency's own files to ground its real API,
even at external_dir_permission=none — because cria's own steer tells it to ("inspect its jar in
your local Maven cache"). Walked: feed-pipeline-java x ornith15 1788684045 hallucinated the OpenCSV
5.9 API across 50+ turns and never compiled, because every read of the resolved opencsv-5.9.jar
under ~/.m2/repository was refused. The bound that actually matters — external WRITES, and reads of
credential-bearing config roots — must stay refused.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import dirguard

WS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith15_codex_poff_1788684045-ydw_f2fy"
M2 = "/home/jesse/.m2/repository/com/opencsv/opencsv/5.9/opencsv-5.9.jar"


def test_javap_on_the_resolved_jar_is_allowed_at_none():
    # The exact grounding action from call 0101, refused for the whole session.
    cmd = f"javap -classpath {M2} com.opencsv.CSVParserBuilder"
    assert dirguard.command_refusal(cmd, "none", WS) is None


def test_unzip_of_the_dep_jar_reads_the_cache_and_writes_locally():
    # Reads the external jar, extracts .class files into the workspace cwd — allowed at none.
    cmd = f"unzip -o -q {M2} 'com/opencsv/CSVParserBuilder.class'"
    assert dirguard.command_refusal(cmd, "none", WS) is None


def test_other_ecosystem_caches_read_at_none():
    for p in ("/home/jesse/.cargo/registry/src/x/serde-1.0/src/lib.rs",
              "/home/jesse/go/pkg/mod/example.com/foo@v1.2.3/foo.go",
              "/usr/lib/python3.12/site-packages/requests/models.py",
              "/home/jesse/.gradle/caches/modules-2/files-2.1/g/a/1.0/a.jar"):
        assert dirguard.command_refusal(f"cat {p}", "none", WS) is None, p
        assert dirguard.path_refusal(p, is_write=False, level="none", workspace=WS) is None, p


def test_credential_roots_are_NOT_treated_as_dep_caches():
    # ~/.m2 root holds settings.xml (server passwords); ~/.cargo root holds credentials.toml;
    # ~/.gem holds credentials; ~/.ssh is secrets. None are the artifact subtree — all still refused.
    for p in ("/home/jesse/.m2/settings.xml",
              "/home/jesse/.cargo/credentials.toml",
              "/home/jesse/.gem/credentials",
              "/home/jesse/.ssh/id_rsa",
              "/home/jesse/.npmrc"):
        assert dirguard.command_refusal(f"cat {p}", "none", WS) is not None, p
        assert dirguard.path_refusal(p, is_write=False, level="none", workspace=WS) is not None, p


def test_a_write_into_the_cache_is_still_refused():
    # Corrupting a machine-shared store is the eaf480f hazard — only `write` may.
    redirect = f"echo x > {M2}"
    assert dirguard.command_refusal(redirect, "none", WS) is not None
    assert dirguard.command_refusal(redirect, "read", WS) is not None
    assert dirguard.path_refusal(M2, is_write=True, level="none", workspace=WS) is not None
    assert dirguard.path_refusal(M2, is_write=True, level="read", workspace=WS) is not None


def test_a_dep_cache_read_does_not_smuggle_a_second_external_write():
    # The dep-cache read must not let a sensitive external WRITE ride along in the same command.
    cmd = f"javap -classpath {M2} com.opencsv.CSVParser > /home/jesse/.ssh/leak"
    assert dirguard.command_refusal(cmd, "none", WS) is not None


def test_write_level_allows_cache_write_as_the_operator_chose():
    assert dirguard.command_refusal(f"echo x > {M2}", "write", WS) is None
