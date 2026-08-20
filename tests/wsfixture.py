"""Build a survey the way the harness would return one.

The survey carries its own completeness proof — a record count and a closing marker — because the
result it rides home on passes through the harness's output cap, and a listing cut in transit is
indistinguishable from a listing of a smaller repo. A test that hand-writes a tree has to carry that
proof too, or it is testing the refusal path rather than the thing it means to test.
"""

from cria import wsview


def survey(tree: str = "", *, progs: str = "", outside: str = "", blob: str = "",
           root: str = "", complete: bool = True, entries: int | None = None) -> str:
    """One survey's output. ``entries`` overrides the record count, for testing the refusal."""
    tree = tree.strip("\n")
    n = wsview.tree_entries(tree) if entries is None else entries
    parts = []
    if root:
        parts += [f"{wsview._SEC_PREFIX}meta{wsview._SEC_SUFFIX}", f"root\t{root}"]
    parts += [f"{wsview._SEC_PREFIX}tree{wsview._SEC_SUFFIX}"]
    if tree:
        parts.append(tree)
    for name, body in (("blob", blob), ("outside", outside), ("progs", progs)):
        parts.append(f"{wsview._SEC_PREFIX}{name}{wsview._SEC_SUFFIX}")
        if body:
            parts.append(body.strip("\n"))
    parts += [f"{wsview._SEC_PREFIX}done{wsview._SEC_SUFFIX}",
              f"entries\t{n}", f"complete\t{1 if complete else 0}",
              wsview.SURVEY_CLOSE]
    return "\n".join(parts)
