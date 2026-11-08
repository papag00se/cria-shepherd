"""Present standalone environment XML as Markdown on the coder wire only.

This is an operator-authorized presentation rule, not an origin check: a user can
send the identical standalone document. Internal messages remain unchanged.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

from . import bodykeys, prompts


def _code(value: str) -> str:
    longest = max((len(m.group()) for m in re.finditer(r"`+", value)), default=0)
    fence = "`" * (longest + 1)
    padded = f" {value} " if value.startswith("`") or value.endswith("`") else value
    return f"{fence}{padded}{fence}"


def _json(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _compact(root) -> str | None:
    """Render only the fully understood environment schema; never discard extensions."""
    def shape(node, tag, children, attrs=()):
        return (node.tag == tag and tuple(node.attrib) == attrs
                and [child.tag for child in node] == children
                and (node.text is None or not node.text.strip(" \t\r\n"))
                and all(child.tail is None or not child.tail.strip(" \t\r\n") for child in node))

    def value(node):
        if node.attrib or len(node) or not node.text or node.text != node.text.strip():
            return None
        if any(ord(c) < 32 or ord(c) == 127 for c in node.text):
            return None
        return _code(node.text)

    if not shape(root, "environment_context", ["cwd", "shell", "current_date", "timezone", "filesystem"]):
        return None
    cwd, shell, date, timezone = (value(n) for n in root[:4])
    fs = root[4]
    if not all((cwd, shell, date, timezone)) or not shape(fs, "filesystem", ["workspace_roots", "permission_profile"]):
        return None
    roots, profile = fs
    if not shape(roots, "workspace_roots", ["root"] * len(roots)) or not len(roots):
        return None
    root_values = [value(n) for n in roots]
    if not all(root_values) or not shape(profile, "permission_profile", ["file_system"], ("type",)):
        return None
    files = profile[0]
    if not shape(files, "file_system", ["entry"] * len(files), ("type",)) or not len(files):
        return None
    entries = []
    for entry in files:
        if not shape(entry, "entry", ["path"], ("access",)):
            return None
        path = value(entry[0])
        access = entry.attrib["access"]
        if not path or not access or access != access.strip() or any(ord(c) < 32 or ord(c) == 127 for c in access):
            return None
        entries.append(f"  - {_code(access)}: {path}")
    profile_type, file_type = profile.attrib["type"], files.attrib["type"]
    if any(not v or v != v.strip() or any(ord(c) < 32 or ord(c) == 127 for c in v)
           for v in (profile_type, file_type)):
        return None
    return prompts.render("environment_compact", cwd=cwd, shell=shell, date=date, timezone=timezone,
                          roots="\n".join(f"  - {v}" for v in root_values),
                          profile=_code(profile_type), filesystem=_code(file_type), entries="\n".join(entries))


def _referenced_mixed_text(text: str) -> bool:
    """Whether a character/entity reference occurs in an element with children.

    Expat's character-data events identify each reference at its original byte
    offset, even if it resolves to whitespace. Attribute and leaf references
    remain values; only references that compact rendering would discard matter.
    """
    raw = text.encode("utf-8")
    parser = expat.ParserCreate()
    stack: list[list[bool]] = []  # [has child, has referenced character data]
    found = False

    def start(_name, _attrs):
        if stack:
            stack[-1][0] = True
        stack.append([False, False])

    def data(_text):
        if stack and raw[parser.CurrentByteIndex:parser.CurrentByteIndex + 1] == b"&":
            stack[-1][1] = True

    def end(_name):
        nonlocal found
        has_child, has_reference = stack.pop()
        found |= has_child and has_reference

    parser.StartElementHandler = start
    parser.CharacterDataHandler = data
    parser.EndElementHandler = end
    parser.Parse(raw, True)
    return found


def render(text: str) -> str | None:
    """Return a structural presentation or abstain when XML content is ambiguous.

    Values are JSON strings inside Markdown code spans; nesting, order, duplicate
    elements and attributes are retained. In the recognized environment schema,
    literal XML S (space, tab, CR, LF) between elements is formatting only when
    no character/entity reference occurs there; any other inter-element text is
    retained by abstaining. Elsewhere all mixed content, including whitespace,
    is left unchanged. Namespaces, comments, XML declarations and DTDs are not
    transformed.
    """
    if not text.strip().startswith("<environment_context") or "<!" in text or "<?" in text:
        return None
    try:
        parser = ET.XMLPullParser(events=("start", "start-ns"))
        parser.feed(text)
        events = list(parser.read_events())
        parser.close()
        if any(event == "start-ns" for event, _ in events):
            return None
        root = next((node for event, node in events if event == "start"), None)
    except (ET.ParseError, ValueError):
        return None
    if root is None or root.tag != "environment_context" or root.attrib:
        return None
    # ElementTree expands even the implicitly declared xml: namespace; reject it
    # instead of erasing xml:space or presenting an expanded name as an attribute.
    if any(not isinstance(n.tag, str) or "{" in n.tag or any("{" in k for k in n.attrib)
           for n in root.iter()):
        return None
    compact = _compact(root)
    if compact is not None:
        try:
            if _referenced_mixed_text(text):
                return None
        except (expat.ExpatError, UnicodeError, ValueError):
            return None
        return compact
    lines = [prompts.load("environment_markdown").strip()]

    def visit(node, depth):
        children = list(node)
        if children and (node.text is not None or any(child.tail is not None for child in children)):
            return False
        attrs = "".join(" " + _code(f"{key}={_json(value)}") for key, value in node.attrib.items())
        line = "  " * depth + "- " + _code(node.tag) + attrs + ":"
        if not children:
            line += " " + _code(_json(node.text or ""))
        lines.append(line)
        return all(visit(child, depth + 1) for child in children)

    if root.text is not None or any(child.tail is not None for child in root):
        return None
    try:
        if not all(visit(child, 0) for child in root):
            return None
    except RecursionError:
        return None
    return "\n".join(lines)


def wire_messages(messages: list[dict]) -> list[dict]:
    out = []
    for message in messages:
        content = message.get("content")
        rendered = (render(content) if message.get("role") == "user" and isinstance(content, str)
                    and bodykeys.ANNOTATION_SOURCE not in message else None)
        out.append({**message, "content": rendered} if rendered is not None else message)
    return out
