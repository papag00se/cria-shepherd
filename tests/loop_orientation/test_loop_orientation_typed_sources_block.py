"""The sources the loop hands the step judge carry a typed kind: web responses and file reads render separately, web unchanged."""
import json

from cria import prompts, research
from cria.fetchfacts import Shape


def _read(path, body, tid="r1"):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": tid, "type": "function", "function": {
                 "name": "read_file", "arguments": json.dumps({"path": path})}}]},
            {"role": "tool", "tool_call_id": tid, "content": body}]


def test_the_loops_sources_keep_their_kind_to_the_rendered_block():
    msgs = _read("pom.xml", "<project/>", "r1") + _read("README.md", "# hello world\n", "r2")
    ledger = {"https://api.example/openapi.json": ("HTTP 200", ("/v1/handle",), (Shape("GET /v1/handle", "{address: string}"),), ())}
    sources = research.sources_read(ledger, msgs)
    assert [type(s) for s in sources] == [research.WebSource, research.FileRead, research.FileRead]
    assert sources[1:] == [research.FileRead("README.md", 14), research.FileRead("pom.xml", 10)]
    block = research._sources_block(sources).splitlines()
    template = prompts.load_map("verify_user")["source_file"]
    assert block[:3] == ["- https://api.example/openapi.json", "    routes it defines: /v1/handle",
                         f"    response fields it defines: {research.fetchfacts.shapes_text((Shape('GET /v1/handle', '{address: string}'),))}"]
    assert block[3:] == prompts.fill(template, path="README.md", chars=14).splitlines() + prompts.fill(template, path="pom.xml", chars=10).splitlines()
    assert not any("response fields" in line for line in block[3:])
