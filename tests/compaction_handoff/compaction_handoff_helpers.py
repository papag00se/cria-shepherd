"""Shared builders: histories of exact token size, typed exchanges, fake lens replies, a rendered survey."""
import json

from cria import bodykeys, denial, groundtruth, prompts, wsview

def asst(n, label="a"):
    return {"role": "assistant", "content": (label + " " + "x" * 4 * n)[:4 * n]}

def history(turns, per_turn=100):
    """system + ``turns`` (assistant, tool) turns of exactly ``per_turn`` estimated tokens each; turn i is labelled ``ti``."""
    out = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        out += [asst(per_turn // 2, f"t{i:03}"), {"role": "tool", "tool_call_id": "c", "content": "y" * 2 * per_turn}]
    return out

def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}

def result(cid, text="ok", outcome=None):
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome is not None:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m

def write(cid, path="src/Importer.java", outcome=denial.LANDED):
    return [call(cid, "write_file", path=path, content="class A {}" * 60), result(cid, "Wrote", outcome)]

def shell(cid, cmd, output="", code=0):
    return [call(cid, "exec_command", cmd=cmd), result(cid, f"Process exited with code {code}\nOutput:\n{output}")]

def chat_reply(content):
    return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})

LENSES = {"retrospective": "RETROSPECTIVE", "scope": "PRESERVES", "files": "NONE", "changes": "NONE",
          "sizes": "NONE", "build": "NONE", "fidelity": "FAITHFUL"}

def lens_of(system):
    for name in LENSES:
        if system.startswith(prompts.load("compaction_validate" + ("" if name == "fidelity" else "_" + name))):
            return name
    return None

def lens_answer(system, **override):
    name = lens_of(system)
    return None if name is None else {**LENSES, **override}[name]

# ornith1.5_9b / Java overnight run 3 (call 0062 briefed "a `REVIEW.md` (235 B)"): the complete survey the writer and judge were shown.
TREE = ("D\t\nD\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nD\ttmp\nD\tdata\n"
        "F\t7\t11796\tsrc/main/java/pipeline/Importer.java\nF\t6\t238754\ttmp/opencsv-5.7.1.jar\nF\t4\t370\tREADME.md\n"
        "F\t3\t1211931\tdata/feed.csv\nF\t2\t235\tdata/feed_messy.csv\nF\t1\t980\tpom.xml\n")

def survey_text(tree=TREE, *, complete=True, changed=False, flavor="briefing"):
    """The workspace inventory cria renders from a harness survey: ``complete=False`` hit its own bound, ``changed`` was overtaken by a mutating command."""
    view = wsview.View("/ws", "compaction-handoff")
    view._ingest_tree(tree, complete=complete)
    if changed:
        view.note_a_mutator_ran()
    token = wsview.bind(view)
    try:
        return groundtruth.workspace_inventory("/ws", flavor=flavor)
    finally:
        wsview.unbind(token)

def survey(tree="", *, root="", blob="", complete=True, entries=None):
    """A harness survey the way the real program emits it (record count and closing marker included, so a cut one is refusable)."""
    tree = tree.strip("\n")
    sec = lambda name: f"{wsview._SEC_PREFIX}{name}{wsview._SEC_SUFFIX}"
    n = wsview.tree_entries(tree) if entries is None else entries
    parts = ([sec("meta"), f"root\t{root}"] if root else []) + [sec("tree")] + ([tree] if tree else [])
    parts += [sec("blob")] + ([blob.strip("\n")] if blob else []) + [sec("outside"), sec("progs"), sec("done"),
                                                                      f"entries\t{n}", f"complete\t{int(complete)}", wsview.SURVEY_CLOSE]
    return "\n".join(parts)
