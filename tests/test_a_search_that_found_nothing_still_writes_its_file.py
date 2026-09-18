"""cria promised a file when it composed the search, so the search must leave one.

`writeproxy` records the spill path at COMPOSE time (`note_search_spill`), and that record is the
sole warrant for the later re-hunt refusal telling the coder "its results were saved to <path> —
READ THAT FILE rather than searching again". The lowered command, however, wrote the file only when
the search returned results. A search that found nothing therefore left a remembered path and no
file, and the warrant pointed at a phantom.

Measured on cart-billing-go x ternary-bonsai-2 (session 01a0b6aa, calls 0008-0012). The first search
returned `no results`. cria then said:

    ⟦ctx:denied⟧ ... Its results were saved to
    ./tmp/reference/search-go.mod_decimal_module_golang.org_x_exp_math_bits_no_github.c-29f04005.txt
    — they are NOT repeated here, so READ THAT FILE rather than searching again

The coder obeyed — "The search results were saved to a reference file. Let me read that file" — and
cria answered "is not there — nothing was read", stacking a second false statement on the first.
Three tool calls went to a file that never existed, and the coder re-ran the same dead query. The
final workspace holds two reference files; the one cria named is not among them.

Two principles, both in cria's own voice: #5b (never state a false fact about the world) and #11b
(a remedy the reader cannot take). The fix is to the WRITE, not to the refusal — cria said it wrote
a file, so cria writes one, and "0 results" is the honest artifact that ends the detour.

The test runs the REAL composed command against a stubbed Brave payload, because the defect lived in
a shell one-liner that no unit test could see by reading Python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from cria import webfetch, writeproxy  # noqa: E402


def _run_composed_search(tmp_path: Path, payload: dict, query: str) -> tuple[str, Path]:
    """Build the command cria really lowers, feed it `payload` instead of Brave, and run it in a
    throwaway workspace. Returns (stdout, the spill path cria recorded for this query)."""
    cmd = writeproxy._search_command({"query": query}, brave_key="test-key")
    target = Path(webfetch.search_spill_name(query))

    # Keep the network out of it: replace the curl with a cat of the stubbed payload. Everything
    # after the first pipe — the parse, the spill write, the printed brief — is cria's real code.
    parse = cmd.split("|", 1)[1]
    stub = tmp_path / "payload.json"
    stub.write_text(json.dumps(payload))

    r = subprocess.run(["bash", "-c", f"cat {stub} |{parse}"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"composed command failed: {r.stderr[-500:]}"
    return r.stdout, tmp_path / target


def test_a_search_with_no_results_still_leaves_the_file_cria_named(tmp_path):
    """THE REGRESSION. Fails before the fix (no file), passes after."""
    out, spill = _run_composed_search(tmp_path, {"web": {"results": []}}, "go decimal module for money")
    assert "no results" in out, out
    assert spill.is_file(), (
        f"cria recorded {spill.name} as this query's spill file and will tell the coder to read it, "
        f"but the search wrote nothing. Contents of the spill dir: "
        f"{[p.name for p in (tmp_path / 'tmp' / 'reference').glob('*')] if (tmp_path / 'tmp' / 'reference').is_dir() else 'dir absent'}"
    )
    assert spill.read_text().startswith("0 results:"), (
        f"the file must state the true outcome so the detour ENDS; got: {spill.read_text()[:120]!r}"
    )


def test_a_search_with_results_still_writes_them(tmp_path):
    """The fix must not cost the normal path: results are still spilled in full."""
    payload = {"web": {"results": [
        {"title": "shopspring/decimal", "url": "https://github.com/shopspring/decimal",
         "description": "Arbitrary-precision fixed-point decimal numbers in Go."},
    ]}}
    out, spill = _run_composed_search(tmp_path, payload, "go decimal library github package")
    assert spill.is_file()
    body = spill.read_text()
    assert body.startswith("1 results:")
    assert "shopspring/decimal" in body
    assert "Arbitrary-precision" in body, "the full description must reach the file, not just the title"


def test_the_recorded_warrant_and_the_written_file_agree(tmp_path):
    """The bug was a disagreement between two places: what cria REMEMBERS it wrote, and what the
    command actually writes. Pin them together for both outcomes."""
    for payload in ({"web": {"results": []}},
                    {"web": {"results": [{"title": "t", "url": "u", "description": "d"}]}}):
        q = f"query for {len(payload['web']['results'])} results"
        _, spill = _run_composed_search(tmp_path, payload, q)
        # `search_spill_name` returns a workspace-relative "./tmp/reference/..." path; compare the
        # normalized forms so the assertion is about the FILE, not about a leading "./".
        remembered = Path(webfetch.search_spill_name(q))
        assert spill.is_file(), f"remembered {remembered}, wrote nothing"
        assert spill == tmp_path / remembered, f"wrote {spill}, remembered {tmp_path / remembered}"
