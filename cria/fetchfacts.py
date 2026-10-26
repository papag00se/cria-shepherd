"""The typed FACTS a fetch establishes, and the one way they become text.

A fetch's facts are gathered from the STRUCTURE cria parsed (an OpenAPI/Swagger doc, an api-catalog linkset) or the protocol
probe observed (an MCP / GraphQL surface) and carried as typed values — never as rendered text that a later consumer has to scan
back into facts. The order is ONE WAY: structure → typed facts → display. Nothing here reads a marker, a header, a fence or an
arrow; the only text this module produces is `text(shape)`, the display of an entry the producer already built.

    Shape    one response-shape entry: its head (``GET /v1/holders/{address}``, or the whole line of a discovery entry or a cap
             note), the route it belongs to, the spec's own path-parameter notes, the generated body (a fenced schema block,
             kept VERBATIM — generated grammar is not flattened), and the field names the structure declared.

A ledger entry is ``(status, routes, shapes, catalog, observed)``: ``routes`` and ``catalog`` are tuples of one-line strings,
``shapes`` a tuple of `Shape`, ``observed`` the protocol a successful discovery probe read.
"""
from __future__ import annotations

from typing import NamedTuple

SHAPE_KEYS = frozenset({"head", "route", "params", "body", "fields"})
FETCH_KEYS = frozenset({"url", "status", "routes", "shapes", "catalog", "observed"})


class Shape(NamedTuple):
    head: str
    route: str = ""
    params: tuple = ()
    body: str = ""
    fields: tuple = ()


def text(shape: Shape) -> str:
    """The display of one entry: the head, the spec's path-parameter notes, then the generated body."""
    head = shape.head
    if shape.params:
        # WORDING IS LOAD-BEARING (see webfetch._endpoint_response_fields): the placeholder is part of the URL and is replaced in place.
        head += f" (replace in the URL path: {'; '.join(shape.params)})"
    return f"{head} returns:\n{shape.body}" if shape.body else head


def report(shape: Shape) -> dict:
    return {"head": shape.head, "route": shape.route, "params": list(shape.params), "body": shape.body,
            "fields": list(shape.fields)}


def _strs(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def valid_report(fx) -> bool:
    """Is ``fx`` exactly a well-typed fetch fact (the shape the producer's record declares)?"""
    if not (isinstance(fx, dict) and set(fx) == FETCH_KEYS):
        return False
    if not all(isinstance(fx[k], str) for k in ("url", "status", "observed")):
        return False
    if not (_strs(fx["routes"]) and _strs(fx["catalog"]) and isinstance(fx["shapes"], list)):
        return False
    return all(isinstance(s, dict) and set(s) == SHAPE_KEYS
               and all(isinstance(s[k], str) for k in ("head", "route", "body"))
               and _strs(s["params"]) and _strs(s["fields"]) for s in fx["shapes"])


def entry_of(fx: dict) -> tuple:
    """The ledger entry for a VALID fetch fact."""
    return (fx["status"], tuple(fx["routes"]),
            tuple(Shape(s["head"], s["route"], tuple(s["params"]), s["body"], tuple(s["fields"])) for s in fx["shapes"]),
            tuple(fx["catalog"]), fx["observed"])


def shapes_text(shapes) -> str:
    """Every entry's display, one after another (a judge's block, a haystack) — never read back as facts."""
    return "\n".join(text(s) for s in shapes or ())


class Field(NamedTuple):
    """One property a response schema DECLARES, as declared: its raw ``name`` (never decorated), whether the schema marks it
    ``required``, its declared ``type`` (``"?"`` when it declares none), an example ``note``, and — for an object cria walks into —
    its ``children``. Optionality and every other fact about the field are fields of this record, never characters of its name."""
    name: str
    required: bool
    type: str
    note: str = ""
    children: "Fields | None" = None


class Fields(NamedTuple):
    """A schema level: the declared ``fields`` shown, and ``elided`` — HOW MANY declared properties the field cap left out (a
    disclosure about the level, not a field and not a name)."""
    fields: tuple = ()
    elided: int = 0

    def __bool__(self) -> bool:
        return bool(self.fields or self.elided)


def field_names(level: Fields) -> tuple:
    """Every declared property name of a parsed schema level, nested ones included, exactly as the schema spelled them: the owned
    `Field.name`s, with nothing decoded from a rendering (a ``real?`` is a property called ``real?``; a name starting ``…`` is
    that property, not a cap note)."""
    out: list[str] = []
    for f in level.fields:
        out.append(f.name)
        if f.children is not None:
            out.extend(field_names(f.children))
    return tuple(out)
