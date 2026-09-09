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


def test_every_fleet_language_cache_root_gets_the_note():
    # All six battery languages: a refused cache ROOT must draw the not-offline note and name a
    # location that is ACTUALLY read-allowed (below), never a location a read would refuse (#5b).
    for cmd, subtree in (("ls ~/.gradle", "~/.gradle/caches"),
                         ("find ~/.cargo -type d", "~/.cargo/registry"),
                         ("find ~/go/pkg -name '*.go'", "~/go/pkg/mod"),
                         ("find ~/.local/lib/python3.14 -name '*.py'", "site-packages"),
                         ("find ~/.gem -name '*.rb'", "~/.gem/ruby"),
                         ("find ~/.npm -name '*.js'", "node_modules")):
        msg = _msg(cmd)
        assert msg is not None and subtree in msg and "not a network" in msg, cmd


def test_the_noted_subtree_is_actually_read_allowed_for_each_language():
    # The note must never point at a place a read would be refused, or it states a false fact.
    for read_cmd in (
        "cat ~/.local/lib/python3.14/site-packages/requests/api.py",
        "cat ~/.local/share/gem/ruby/3.4.0/gems/countries-8/lib/c.rb",
        "cat /usr/lib/ruby/gems/3.4.0/gems/money-6/lib/money.rb",
        "cat ~/.local/share/mise/installs/node/26.7.0/lib/node_modules/express/index.js",
    ):
        assert _msg(read_cmd) is None, read_cmd


def test_language_credentials_stay_refused():
    # A read of the manager's credential/config file is still refused for every language.
    for cred in ("/home/u/.gem/credentials", "/home/u/.npmrc", "/home/u/.bundle/config",
                 "/home/u/.m2/settings.xml", "/home/u/.cargo/credentials.toml"):
        assert dirguard.path_refusal(cred, is_write=False, level="none", workspace="/ws") is not None, cred


def test_a_write_into_a_gem_or_node_cache_is_still_refused():
    for cache_write in ("/home/u/.gem/ruby/3.4.0/gems/foo/x.rb",
                        "/home/u/.local/share/mise/installs/node/26/lib/node_modules/e/i.js"):
        assert dirguard.path_refusal(cache_write, is_write=True, level="none", workspace="/ws") is not None, cache_write


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
