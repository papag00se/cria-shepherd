"""A refused package-manager cache ROOT (`find ~/.m2`) must not read as "offline".

Walked: feed-pipeline-java x ornith15 1788933193. The coder ran `find ~/.m2` to discover the Maven
cache layout, drew the bare "outside the workspace" refusal, and reasoned "there's likely NO network
access" — burning ~5 early turns hand-building a scratch ./tmp/m2repo while the network was fine (it
downloaded opencsv 5.8 the same session). The refusal for a dependency-cache ROOT must name the
readable artifact subtree and state this is a PATH limit, not a network one — the reader-facing
complement of a00ce45 (which allowed the artifact subtree itself).
"""
from cria import dirguard


def _msg(command, level="none", workspace="/ws"):
    return dirguard.command_refusal(command, level, workspace)


def test_find_m2_root_refusal_names_the_readable_subtree_and_denies_offline():
    msg = _msg("find ~/.m2 -name '*.jar'")
    assert msg is not None, "find ~/.m2 (a root read) is still refused — the root holds credentials"
    # The note that ends the offline rabbit hole: readable artifact subtree + not-a-network-limit.
    assert "~/.m2/repository" in msg
    assert "not a network" in msg
    assert "offline" in msg.lower()


def test_gradle_and_cargo_roots_get_the_same_note():
    for cmd, subtree in (("ls ~/.gradle", "~/.gradle/caches"),
                         ("find ~/.cargo -type d", "~/.cargo/registry")):
        msg = _msg(cmd)
        assert msg is not None and subtree in msg, cmd


def test_the_artifact_subtree_itself_is_still_allowed_not_noted():
    # a00ce45: a READ under the artifact subtree is allowed outright — no refusal, so no note.
    assert _msg("javap -classpath ~/.m2/repository/com/opencsv/opencsv/5.8/opencsv-5.8.jar") is None


def test_a_plain_external_path_gets_no_depcache_note():
    msg = _msg("cat /etc/passwd")
    assert msg is not None
    assert "network" not in msg and "repository" not in msg


def test_reading_a_credential_under_m2_still_refused_but_points_at_the_cache():
    # settings.xml is withheld (credentials), but the note still correctly says the ARTIFACT cache is
    # readable and the environment is not offline — an accurate, harmless redirect.
    msg = dirguard.path_refusal("/home/u/.m2/settings.xml", is_write=False, level="none",
                                workspace="/ws")
    assert msg is not None and "~/.m2/repository" in msg
