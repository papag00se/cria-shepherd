"""cleanup analysis for the extra languages (C, C++, Swift, Objective-C, Dart, Lua, Perl, R, Julia, PowerShell) on a broad matrix
of inert source rows (never run): a represented external/root mutation blocks, the same call inside the project is WITHIN_SCOPE,
`write` permission lifts only the external rule, and comments, quoted examples, shadowed names, unevaluated forms and dynamic
targets never block. A tool call (write_file/edit_file) then goes through real lowering and is withheld."""
import json
import subprocess
import unittest.mock as mock

import pytest

from cria import writeproxy
from cria.cleanupsafety import analyze

WS = '/workspace'
# (suffix, prelude, mutation of the literal /outside/data)
CASES = [('.c', '#include <stdio.h>\n', 'remove("/outside/data");'), ('.cpp', '#include <filesystem>\n', 'std::filesystem::remove_all("/outside/data");'),
         ('.swift', 'import Foundation\n', 'try FileManager.default.removeItem(atPath: "/outside/data")'),
         ('.m', '#import <Foundation/Foundation.h>\n', '[[NSFileManager defaultManager] removeItemAtPath:@"/outside/data" error:NULL];'),
         ('.dart', "import 'dart:io';\n", 'Directory("/outside/data").deleteSync(recursive: true);'), ('.lua', '', 'os.remove("/outside/data")'),
         ('.pl', 'use File::Path qw(remove_tree);\n', 'remove_tree("/outside/data");'), ('.R', '', 'unlink("/outside/data", recursive=TRUE)'),
         ('.jl', '', 'rm("/outside/data"; recursive=true)'), ('.ps1', '', 'Remove-Item -LiteralPath "/outside/data" -Recurse')]
# (suffix, source): blocked at permission `none`
BLOCKS = [('.c', '#include <stdio.h>\nfopen("/outside/data", "w");'), ('.cpp', '#include <cstdio>\nstd::fopen("/outside/data", "r+");'),
          ('.cpp', '#include <fstream>\nvoid clean() { std::ofstream stream("/outside/data"); }'),
          ('.swift', 'import Foundation\nFileManager.default.createFile(atPath: "/outside/data", contents: nil)'),
          ('.m', '#import <Foundation/Foundation.h>\n[[NSFileManager defaultManager] createFileAtPath:@"/outside/data" contents:nil attributes:nil];'),
          ('.dart', "import 'dart:io';\nFile('/outside/data').writeAsStringSync('data');"), ('.lua', 'io.open("/outside/data", "w")'),
          ('.pl', 'open(my $fh, ">", "/outside/data");'), ('.pl', 'unlink "/outside/data";'), ('.pl', 'unlink("/workspace/owned", "/outside/data");'),
          ('.pl', 'use File::Path qw(remove_tree);\nremove_tree "/outside/data" if $enabled;'), ('.R', 'writeLines("data", con="/outside/data")'),
          ('.R', 'file.remove("/workspace/owned", "/outside/data")'), ('.jl', 'open("/outside/data"; write=true)'),
          ('.ps1', 'Set-Content -LiteralPath "/outside/data" -Value "data"'), ('.ps1', 'Remove-Item -LiteralPath "/workspace/owned", "/outside/data" -Recurse'),
          ('.ps1', 'REMOVE-ITEM -LITERALPATH "/outside/data" -RECURSE -WHATIF:$false'),
          ('.dart', "import 'dart:io';\nnew Directory('/outside/data').deleteSync(recursive:true);")]
# (suffix, source): a recursive root deletion, blocked even at `write` as a PROVEN root finding
ROOTS = [('.cpp', '#include <filesystem>\nvoid clean() { if (enabled) std::filesystem::remove_all("/"); }'),
         ('.swift', 'import Foundation\nfunc clean() { if enabled { try FileManager.default.removeItem(atPath: "/") } }'),
         ('.m', '#import <Foundation/Foundation.h>\nvoid clean() { if (enabled) [[NSFileManager defaultManager] removeItemAtPath:@"/" error:NULL]; }'),
         ('.dart', "import 'dart:io';\nvoid clean() { if (enabled) Directory('/').delete(recursive: true); }"),
         ('.pl', 'use File::Path qw(remove_tree);\nsub clean { if ($enabled) { remove_tree("/"); } }'),
         ('.R', 'clean <- function() { if (enabled) unlink("/", recursive=TRUE) }'), ('.jl', 'function clean()\n if enabled\n rm("/"; recursive=true)\n end\nend'),
         ('.ps1', 'function clean { if ($enabled) { Remove-Item -LiteralPath "/" -Recurse } }'),
         ('.swift', 'import Foundation\ntry FileManager.default.removeItem(at: URL(fileURLWithPath: "/"))'),
         ('.cpp', '#include <filesystem>\nstd::filesystem::remove_all(std::filesystem::path("/"));'),
         ('.R', 'quote(unlink("/", recursive=TRUE)); unlink("/", recursive=TRUE)'),    # an unevaluated example hides no separate real call
         ('.cpp', '#include <filesystem>\nsizeof(std::filesystem::remove_all("/")); std::filesystem::remove_all("/");'),
         ('.jl', 'example = :(rm("/"; recursive=true)); rm("/"; recursive=true)'), ('.jl', '@show(enabled); rm("/"; recursive=true)')]
# (suffix, source): analysed, never blocked at `none`
PASSES = [('.lua', 'io.open("/outside/data")'), ('.pl', 'open(my $fh, "<", "/outside/data");'),
('.dart', "import 'custom.dart';\nDirectory('/').delete(recursive:true);"),
          ('.lua', 'function clean(os) os.remove("/outside/data") end'),           ('.ps1', 'function Remove-Item { param($LiteralPath) }; Remove-Item -LiteralPath "/" -Recurse'),
          # comments and quoted examples are text, not operations
          ('.c', '#include <stdio.h>\n/* remove("/outside/data"); */'), ('.cpp', '#include <filesystem>\nauto e = u8R"tag(a quote " std::filesystem::remove_all("/"))tag";'),
          ('.swift', 'import Foundation\nlet e = """\nFileManager.default.removeItem(atPath: "/")\n"""'),
          ('.m', '#import <Foundation/Foundation.h>\n// [[NSFileManager defaultManager] removeItemAtPath:@"/" error:NULL];'),
          ('.dart', "import 'dart:io';\nvar e = '''Directory('/').delete(recursive:true);''';"), ('.lua', '--[=[os.remove("/outside/data")]=]'),
          ('.lua', 'e = [=[os.remove("/outside/data")]=]'), ('.pl', '=pod\nremove_tree("/");\n=cut\n'), ('.pl', r'my $e = q{\} unlink("/outside/data")};'), ('.R', '# unlink("/", recursive=TRUE)'),
          ('.jl', '#= #= nested =# rm("/"; recursive=true) =#'), ('.ps1', "$e = @'\nRemove-Item -LiteralPath '/' -Recurse\n'@"),
          ('.ps1', '<# Remove-Item -LiteralPath "/" -Recurse #>'),
          # identity or evaluation is ambiguous
          ('.c', '#include <stdio.h>\n#define remove no_op\nremove("/outside/data");'),
          ('.swift', 'import Foundation\nclass FileManager {}\nFileManager.default.removeItem(atPath:"/")'),
          ('.dart', "import 'dart:io';\ncustom.Directory('/').delete(recursive:true);"),
          ('.lua', 'os.remove = custom; os.remove("/outside/data")'),           ('.pl', 'my $e = <<\'END\';\nunlink("/outside/data");\nEND\n'), ('.pl', '__DATA__\nunlink("/outside/data");'),
          ('.R', 'expression(unlink("/", recursive=TRUE))'), ('.jl', '@custom(rm("/"; recursive=true))'),
          ('.jl', 'e = quote\nrm("/"; recursive=true)\nend'), ('.jl', 'open("/outside/data"; write=enabled)'),
          ('.ps1', 'set-alias Remove-Item Write-Output; Remove-Item -Path "/" -Recurse'), ('.ps1', 'Remove-Item -Path "/" -Recurse -WhatIf:$preview')]
# interpolated or Windows targets are UNKNOWN, never a literal proof
UNKNOWNS = [('.swift', r'import Foundation; FileManager.default.removeItem(atPath:"/\(target)")'), ('.pl', 'unlink("/@targets");'), ('.ps1', r"Remove-Item -LiteralPath 'C:\' -Recurse")]
UNTERMINATED = [('.c', '#include <stdio.h>\nfopen("/outside/data", "r"); /*'), ('.lua', 'e = [=[os.remove("/outside/data")'), ('.ps1', "$x = @'\nRemove-Item -Path '/' -Recurse")]


@pytest.mark.parametrize('suffix,prelude,op', CASES)
def test_each_language_blocks_external_scopes_project_and_honours_write_permission(suffix, prelude, op):
    path = 'cleanup' + suffix
    result = analyze(path, prelude + op, WS)
    assert result.coverage == 'supported-subset' and result.blocked
    assert any(f.rule == 'external' and f.targets == ('/outside/data',) for f in result.findings)
    dynamic = analyze(path, prelude + op.replace('@"/outside/data"', 'target').replace('"/outside/data"', 'target'), WS)
    assert not dynamic.blocked and any(f.confidence == 'UNKNOWN' for f in dynamic.findings)
    safe = analyze(path, prelude + op.replace('/outside/data', '/workspace/scratch'), WS)
    assert not safe.blocked and any(f.confidence == 'WITHIN_SCOPE' for f in safe.findings)
    assert not analyze(path, prelude + op, WS, 'write').blocked
    assert not analyze('example' + suffix, 'example(")", "/outside/data")', WS).blocked      # a quoted ')' is not parser structure


@pytest.mark.parametrize('suffix,source', BLOCKS)
def test_real_call_forms_that_write_or_delete_outside_are_blocked(suffix, source):
    assert analyze('cleanup' + suffix, source, WS).blocked


@pytest.mark.parametrize('suffix,source', ROOTS)
def test_recursive_root_deletion_survives_control_flow_and_write_permission(suffix, source):
    result = analyze('cleanup' + suffix, source, WS, 'write')
    assert result.blocked and sum(f.confidence == 'PROVEN' and f.rule == 'root' for f in result.findings) == 1


@pytest.mark.parametrize('suffix,source', PASSES)
def test_non_mutations_text_and_ambiguous_identity_never_block(suffix, source):
    assert not analyze('cleanup' + suffix, source, WS).blocked


@pytest.mark.parametrize('suffix,source', UNKNOWNS)
def test_interpolated_and_windows_targets_are_unknown_not_proofs(suffix, source):
    result = analyze('cleanup' + suffix, source, WS)
    assert not result.blocked and result.coverage == 'supported-subset' and any(f.confidence == 'UNKNOWN' for f in result.findings)


@pytest.mark.parametrize('suffix,source', UNTERMINATED)
def test_unterminated_lexical_regions_and_the_token_budget_are_unverified_not_clean(suffix, source):
    result = analyze('cleanup' + suffix, source, WS)
    assert result.coverage == 'invalid-source' and not result.blocked
    assert analyze('cleanup.lua', 'x=1\n' * 6000, WS).coverage == 'analysis-limit'


@pytest.mark.parametrize('suffix,prelude,op', CASES)
@pytest.mark.parametrize('tool', ['write_file', 'edit_file'])
def test_real_lowering_withholds_each_language_without_executing_the_source(tmp_path, suffix, prelude, op, tool):
    path, previous, candidate = 'cleanup' + suffix, prelude + op.replace('/outside/data', '/workspace/scratch'), prelude + op
    args = ({'path': path, 'content': candidate} if tool == 'write_file'
            else {'path': path, 'old_string': '/workspace/scratch', 'new_string': '/outside/data'})
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'one', 'type': 'function', 'function': {'name': tool, 'arguments': json.dumps(args)}}]}}]}
    view = writeproxy.wsview.View(WS)
    view.note_read(path, previous)
    events = []
    log = type('L', (), {'emit': lambda self, *a, **k: events.append((a, k))})()
    with mock.patch.object(writeproxy.wsview, 'current', return_value=view):
        writeproxy.translate_outbound(completion, {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}},
                                      injected={tool}, workspace_root=WS, external_dir_permission='none', rlog=log)
    (tmp_path / path).write_text(previous)
    cmd = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    run = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, text=True)      # the lowered program really refuses
    assert 'withheld' in cmd and run.returncode == 1 and 'outside the permitted workspace boundary' in run.stdout + run.stderr
    assert (tmp_path / path).read_text() == previous              # nothing was written
    assert any(a[0] == 'safety.cleanup_review' and k['verdict'] == 'UNSAFE' for a, k in events)
