"""Wave 9 coverage: cleanup analysis arms the matrices do not reach (never run, only analysed).

Every row is (file, source, blocked, the single finding's confidence): a path the script itself owns (a temp dir it made,
`tempnam`) is WITHIN_SCOPE; a wildcard import, an early raise, a non-literal option bag or an escaped quote makes the
target UNKNOWN; code that may not run is POSSIBLE; only a literal external/root target in code that runs is PROVEN.
"""
import pytest

from cria.cleanupsafety import analyze

JS = 'const fs=require("fs");\n'
ROWS = [
    ("f.py", 'import shutil,os\nshutil.rmtree(os.path.normpath("/external/../external"))', True, "PROVEN"),
    ("f.py", 'import shutil\nfrom os import *\nshutil.rmtree("/")', False, "UNKNOWN"),                       # a star import rebinds every name
    ("f.py", 'import tempfile,os,shutil\nf=tempfile.NamedTemporaryFile("w")\nshutil.rmtree(os.path.dirname(f.name))', False, "UNKNOWN"),
    ("f.py", 'import shutil\nraise SystemExit\nshutil.rmtree("/")', False, "UNKNOWN"),                       # never reached
    ("f.py", 'import shutil\np="/external"\nwhile x:\n    p="/project/a"\nshutil.rmtree(p)', False, "POSSIBLE"),   # a loop may have rebound p
    ("f.py", 'import tempfile,shutil\ndef mk():\n    if x:\n        return 1\nshutil.rmtree(tempfile.mkdtemp())', False, "WITHIN_SCOPE"),
    ("f.rs", 'use std::fs;\nfn main(){ fs::remove_dir_all("/external").unwrap(); }', False, "POSSIBLE"),
    ("f.rs", 'use std::fs::remove_dir_all;\nfn main(){ remove_dir_all("/external").unwrap(); }', False, "POSSIBLE"),
    ("f.rs", 'use std::fs::{self, File};\nfn main(){ fs::remove_dir_all("/external").unwrap(); }', False, "UNKNOWN"),   # a brace import binds nothing certain
    ("f.js", JS + 'fs.rmSync("/external", {recursive:true, maxRetries:3});', False, "POSSIBLE"),              # an option the analysis does not know
    ("f.js", JS + 'fs.rmSync("/external", {"recursive":true});', True, "PROVEN"),
    ("f.js", JS + 'const d=fs.mkdtempSync("/tmp/x-");\nfs.rmSync(d,{recursive:true});', False, "WITHIN_SCOPE"),
    ("f.js", JS + 'fs.rmSync("/external\\n");', True, "PROVEN"),
    ("f.js", JS + "fs.rmSync('/ex\\'ternal');", False, "UNKNOWN"),                                              # an escaped single-quoted body is not a certain literal
    ("f.php", '<?php\n$f=tempnam("/tmp","x");\nunlink($f);', False, "WITHIN_SCOPE"),
    ("f.php", '<?php\nunlink("/external/$x");', False, "UNKNOWN"),                                              # an interpolated string is not a literal
]


@pytest.mark.parametrize("path,source,blocked,confidence", ROWS)
def test_analysis_blocks_only_what_it_can_prove_and_labels_the_rest(path, source, blocked, confidence):
    result = analyze(path, source, "/project")
    assert (result.blocked, [f.confidence for f in result.findings]) == (blocked, [confidence])


def test_an_analysis_over_the_token_budget_declares_the_limit_instead_of_guessing():
    result = analyze("big.js", "x = 1;\n" * 12000, "/project")
    assert (result.blocked, result.coverage, result.findings) == (False, "analysis-limit", ())
