"""Per-language cleanup analysis (cria.cleanup_python / cleanup_languages / cleanup_extra via cleanupsafety.analyze): a represented mutation of an
external/root/shared-temp path is PROVEN and blocked; project paths, dynamic targets, shadowed bindings and unproven control flow never are."""
import pytest
from cria.cleanupsafety import analyze

WS = '/project'

PY_BLOCKED = [   # resolved mutations (python): alias, os.path/pathlib joins, temp parents, zero-argument helpers, open modes
    'import shutil as s\ns.rmtree("/")', 'from shutil import rmtree as erase\nerase("/external")',
    'from pathlib import Path\np=Path("/external") / "file"\np.write_text("x")', 'from pathlib import Path\nPath("/external/file").parent.rmdir()',
    'import tempfile,os,shutil\nf=tempfile.NamedTemporaryFile()\nshutil.rmtree(os.path.dirname(f.name))',
    'import shutil\ndef target():\n return "/"\nshutil.rmtree(target())', 'open("/external/file", "w")', 'import io\nio.open("/external/file", mode="a")',
    'import shutil\nclass C:\n def cleanup(self):\n  shutil.rmtree("/")',
    'import shutil\ntry:\n    shutil.rmtree("/")\nfinally:\n    pass', 'import shutil\ntry:\n    pass\nfinally:\n    shutil.rmtree("/")',
    'import shutil\ntry:\n    x=1\nexcept OSError:\n    pass\nelse:\n    shutil.rmtree("/")', 'import shutil\nwith open("x") as f:\n    shutil.rmtree("/")',
    'import tempfile,os,shutil\nshutil.rmtree(os.path.dirname(tempfile.mkstemp()[1]))', 'import shutil\nshutil.rmtree("/external" if x else "/other")',
]
PY_NOT_BLOCKED = [   # the identity/value is not what it looks like, or the code cannot be certified to run
    'import shutil\ndef f(shutil):\n shutil.rmtree("/")', 'import shutil\nshutil=custom()\nshutil.rmtree("/")', 'import shutil\ns=shutil\nshutil.rmtree=custom\ns.rmtree("/")',
    'import os\np="/external"\nexec("p = unknown()")\nos.unlink(p)', 'import os\np="/external"\n(p:="/project/owned")\nos.unlink(p)',
    'import shutil\nfor x in []:\n shutil.rmtree("/")', 'import shutil\nif False:\n shutil.rmtree("/")', 'open("/etc/hosts", "r")',
    'import os,shutil,tempfile\nd=tempfile.mkdtemp()\nfd,p=tempfile.mkstemp(dir=d)\nshutil.rmtree(os.path.dirname(p))',     # a parent the script itself owns
    'import tempfile,shutil\nwith tempfile.TemporaryDirectory() as d:\n shutil.rmtree(d)',
    'import shutil\ntry:\n    pass\nexcept OSError:\n    shutil.rmtree("/")', 'import shutil\nx=["/external"]\nshutil.rmtree(x[0])',
    'def f():\n return\n import shutil\n shutil.rmtree("/")', 'class Thing:\n def unlink(self): pass\nx=Thing()\nx.unlink()',
]

@pytest.mark.parametrize('source', PY_BLOCKED)
def test_python_mutations_that_resolve_to_an_external_root_or_shared_temp_target_are_blocked(source):
    """The abstract interpreter follows aliases, joins, parents and zero-argument helpers to the literal target; resolved => PROVEN."""
    assert analyze('f.py', source, WS).blocked

@pytest.mark.parametrize('source', PY_NOT_BLOCKED)
def test_python_shadowed_rebound_dynamic_or_unreachable_code_is_never_blocked(source):
    """Rebinding, shadowing, exec, never-run branches and self-owned temp parents give no proof, so no refusal."""
    assert not analyze('f.py', source, WS).blocked

def test_a_loop_body_that_may_not_run_is_possible_not_proven_and_still_knows_its_literal_targets():
    """cria cannot certify that a for-body executes: the deletion is POSSIBLE (never refuses the write), and the loop variable still carries the listed literals."""
    for source in ('import shutil\nfor x in ["a", "b"]:\n shutil.rmtree("/")', 'import os\nfor p in ["/external/a", "/external/b"]:\n os.unlink(p)'):
        result = analyze('f.py', source, WS)
        assert not result.blocked and {f.confidence for f in result.findings} == {'POSSIBLE'}, source

ROOT = [   # permission 'write' lifts the external rule, so only the ROOT rule remains: recursive deletion of '/' blocks, a non-recursive call does not
    ('f.js', 'const fs=require("fs");\nfs.rmSync("/", {recursive:true});', 'const fs=require("fs");\nfs.rmSync("/");'),
    ('f.go', 'package main\nimport "os"\nfunc main() { os.RemoveAll("/") }', 'package main\nimport "os"\nfunc main() { os.Remove("/") }'),
    ('f.cs', 'class C { void F() { System.IO.Directory.Delete("/", true); } }', 'class C { void F() { System.IO.Directory.Delete("/"); } }'),
    ('f.ex', 'File.rm_rf("/")', 'File.rm("/")'),
]

@pytest.mark.parametrize('path,recursive,single', ROOT)
def test_recursive_root_deletion_is_blocked_even_with_external_write_permission_and_a_single_file_call_is_not(path, recursive, single):
    """Recursion is part of the API contract per language (fs.rm needs {recursive}, Directory.Delete needs true, os.RemoveAll/File.rm_rf always)."""
    assert analyze(path, recursive, WS, 'write').blocked and not analyze(path, single, WS, 'write').blocked

def test_a_root_deletion_through_an_unimported_or_rebound_api_is_unresolved_not_proven():
    """Identity must be known before it counts: `os` rebound to something else, or never imported, is no proof of the os package."""
    for source in ('package main\nimport "os"\nfunc main() { os := custom; os.RemoveAll("/") }', 'package main\nfunc main() { os.RemoveAll("/") }'):
        result = analyze('f.go', source, WS, 'write')
        assert not result.blocked and {(f.confidence, f.rule) for f in result.findings} == {('UNKNOWN', 'unresolved')}, source
    assert not analyze('f.js', 'fs.rmSync("/", {recursive:true});', WS, 'write').blocked

@pytest.mark.parametrize('suffix,prelude,call,blocked', [
    ('.c', '#include <stdio.h>\n', 'remove("/outside/data");', True),                   # the real libc function
    ('.c', '#include <stdio.h>\n', 'obj->remove("/outside/data");', False),             # a callback member, invisible to cria
    ('.c', '#include <stdio.h>\n', 'obj->a->remove("/outside/data");', False),
    ('.c', '#include <stdio.h>\n', 'if (a->b) remove("/outside/data");', True),         # an arrow elsewhere does not hide the call
    ('.c', '#include <stdio.h>\n', 'obj.remove("/outside/data");', False),
    ('.c', '#include <stdio.h>\n', 'char *s = "a->remove(/outside/data)";', False),     # prose in a string literal
    ('.cpp', '#include <cstdio>\n', 'ptr->remove("/outside/data");', False),
    ('.cpp', '#include <cstdio>\n', 'std::remove("/outside/data");', True),
    ('.php', '<?php ', '$o->unlink("/outside/data");', False),
    ('.php', '<?php ', 'unlink("/outside/data");', True),
    ('.pl', 'use File::Path qw(remove_tree);\n', '$o->remove_tree("/outside/data");', False),
    ('.pl', 'use File::Path qw(remove_tree);\n', 'remove_tree("/outside/data");', True),
])
def test_an_arrow_member_call_named_like_a_delete_function_is_not_that_function(suffix, prelude, call, blocked):
    """`obj->remove("/outside/data")` (C/C++/PHP/Perl member or callback call) mutates nothing cria can see, so it is not PROVEN; the free function still is.
    (cleanup_extra/cleanup_languages read only `.` and `::` as member access, so C `->` and PHP/Perl `$o->unlink(...)` were blocked as the real call.)"""
    assert analyze('x' + suffix, prelude + call, WS).blocked is blocked

EXTRA = [   # language, suffix, declaration prelude, a mutation with a literal external target
    ('c', '.c', '#include <stdio.h>\n', 'remove("/outside/data");'), ('cpp', '.cpp', '#include <filesystem>\n', 'std::filesystem::remove_all("/outside/data");'),
    ('swift', '.swift', 'import Foundation\n', 'try FileManager.default.removeItem(atPath: "/outside/data")'),
    ('objective-c', '.m', '#import <Foundation/Foundation.h>\n', '[[NSFileManager defaultManager] removeItemAtPath:@"/outside/data" error:NULL];'),
    ('dart', '.dart', "import 'dart:io';\n", 'Directory("/outside/data").deleteSync(recursive: true);'), ('lua', '.lua', '', 'os.remove("/outside/data")'),
    ('perl', '.pl', 'use File::Path qw(remove_tree);\n', 'remove_tree("/outside/data");'), ('r', '.R', '', 'unlink("/outside/data", recursive=TRUE)'),
    ('julia', '.jl', '', 'rm("/outside/data"; recursive=true)'), ('powershell', '.ps1', '', 'Remove-Item -LiteralPath "/outside/data" -Recurse'),
]

@pytest.mark.parametrize('language,suffix,prelude,operation', EXTRA)
def test_each_additional_language_blocks_an_external_target_passes_a_project_target_and_never_invents_a_dynamic_one(language, suffix, prelude, operation):
    """Per adapter: external literal => blocked (lifted by write permission); project literal => WITHIN_SCOPE; a variable target => UNKNOWN, not blocked."""
    result = analyze('x' + suffix, prelude + operation, WS)
    assert result.language == language and result.coverage == 'supported-subset' and result.blocked
    assert any(f.rule == 'external' and f.targets == ('/outside/data',) for f in result.findings) and not analyze('x' + suffix, prelude + operation, WS, 'write').blocked
    within = analyze('x' + suffix, prelude + operation.replace('/outside/data', '/project/scratch'), WS)
    assert not within.blocked and any(f.confidence == 'WITHIN_SCOPE' for f in within.findings)
    dynamic = analyze('x' + suffix, prelude + operation.replace('@"/outside/data"', 'target').replace('"/outside/data"', 'target'), WS)
    assert not dynamic.blocked and any(f.confidence == 'UNKNOWN' for f in dynamic.findings)

@pytest.mark.parametrize('suffix,source,blocked', [
    ('.c', '#include <stdio.h>\nfopen("/outside/data", "w");', True), ('.c', '#include <stdio.h>\nfopen("/outside/data", "r");', False),
    ('.c', '#include <unistd.h>\nunlink("/outside/data");', True), ('.c', '#include <unistd.h>\nrmdir("/outside/data");', True),
    ('.c', '#include <stdio.h>\nint n = sizeof(remove("/outside/data"));', False),                        # unevaluated operand
    ('.cpp', '#include <cstdio>\nitems.remove("/outside/data");', False),                                  # a method named remove is not the free function
    ('.lua', 'io.open("/outside/data", "w")', True), ('.lua', 'io.open("/outside/data")', False),
])
def test_write_modes_unevaluated_operands_and_member_calls_decide_whether_a_c_style_call_mutates(suffix, source, blocked):
    """fopen/io.open mutate only in a writing mode; unlink/rmdir need their header; sizeof() and `.remove` are not the libc call."""
    assert analyze('x' + suffix, source, WS).blocked is blocked

def test_kotlin_extension_deleteRecursively_on_the_root_is_a_root_finding_though_a_function_body_keeps_it_possible():
    """The imported extension on a receiver is the recursive API: root finding (POSSIBLE inside fun {}), where a plain File.delete resolves to nothing."""
    imports = 'import kotlin.io.path.deleteRecursively\nimport kotlin.io.path.Path\n'
    found = analyze('f.kt', imports + 'fun f() {\nval p=Path("/"); p.deleteRecursively()\n}', WS, 'write')
    assert [(f.rule, f.confidence) for f in found.findings] == [('root', 'POSSIBLE')]
    assert [f.rule for f in analyze('f.kt', imports + 'fun f() {\nval p=Path("/"); p.toFile().delete()\n}', WS, 'write').findings] == ['unresolved']
