"""Inert candidate text only: never compile, import or execute these programs."""
import json
from unittest.mock import Mock, patch
import pytest
from cria.cleanupsafety import analyze
from cria import writeproxy

WORKSPACE = '/workspace'

# language, suffix, import/declaration prelude, mutation with a literal target.
CASES = [
    ('c', '.c', '#include <stdio.h>\n', 'remove("/outside/data");'),
    ('cpp', '.cpp', '#include <filesystem>\n', 'std::filesystem::remove_all("/outside/data");'),
    ('swift', '.swift', 'import Foundation\n', 'try FileManager.default.removeItem(atPath: "/outside/data")'),
    ('objective-c', '.m', '#import <Foundation/Foundation.h>\n', '[[NSFileManager defaultManager] removeItemAtPath:@"/outside/data" error:NULL];'),
    ('dart', '.dart', "import 'dart:io';\n", 'Directory("/outside/data").deleteSync(recursive: true);'),
    ('lua', '.lua', '', 'os.remove("/outside/data")'),
    ('perl', '.pl', 'use File::Path qw(remove_tree);\n', 'remove_tree("/outside/data");'),
    ('r', '.R', '', 'unlink("/outside/data", recursive=TRUE)'),
    ('julia', '.jl', '', 'rm("/outside/data"; recursive=true)'),
    ('powershell', '.ps1', '', 'Remove-Item -LiteralPath "/outside/data" -Recurse'),
]

@pytest.mark.parametrize('language,suffix,prelude,operation', CASES)
def test_external_mutation_and_within_scope_counterpart(language, suffix, prelude, operation):
    result = analyze('cleanup' + suffix, prelude + operation, WORKSPACE)
    assert result.language == language
    assert result.coverage == 'supported-subset'
    assert result.blocked, result
    assert any(f.rule == 'external' and f.targets == ('/outside/data',) for f in result.findings)
    safe = analyze('cleanup' + suffix, prelude + operation.replace('/outside/data', '/workspace/scratch'), WORKSPACE)
    assert not safe.blocked, safe
    assert any(f.confidence == 'WITHIN_SCOPE' for f in safe.findings), safe
    allowed = analyze('cleanup' + suffix, prelude + operation, WORKSPACE, 'write')
    assert not allowed.blocked, allowed

@pytest.mark.parametrize('language,suffix,prelude,operation', CASES)
def test_dynamic_target_is_not_invented(language, suffix, prelude, operation):
    source = prelude + operation.replace('@"/outside/data"', 'target').replace('"/outside/data"', 'target')
    result = analyze('cleanup' + suffix, source, WORKSPACE)
    assert not result.blocked, result
    assert any(f.confidence == 'UNKNOWN' for f in result.findings), result

@pytest.mark.parametrize('suffix,source', [
    ('.cpp', '#include <filesystem>\nvoid clean() { if (enabled) std::filesystem::remove_all("/"); }'),
    ('.swift', 'import Foundation\nfunc clean() { if enabled { try FileManager.default.removeItem(atPath: "/") } }'),
    ('.m', '#import <Foundation/Foundation.h>\nvoid clean() { if (enabled) [[NSFileManager defaultManager] removeItemAtPath:@"/" error:NULL]; }'),
    ('.dart', "import 'dart:io';\nvoid clean() { if (enabled) Directory('/').delete(recursive: true); }"),
    ('.pl', 'use File::Path qw(remove_tree);\nsub clean { if ($enabled) { remove_tree("/"); } }'),
    ('.R', 'clean <- function() { if (enabled) unlink("/", recursive=TRUE) }'),
    ('.jl', 'function clean()\n if enabled\n rm("/"; recursive=true)\n end\nend'),
    ('.ps1', 'function clean { if ($enabled) { Remove-Item -LiteralPath "/" -Recurse } }'),
])
def test_recursive_root_survives_control_flow_and_external_permission(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE, 'write')
    assert result.blocked, result
    assert any(f.confidence == 'PROVEN' and f.rule == 'root' for f in result.findings), result

@pytest.mark.parametrize('suffix,source', [
    ('.c', '#include <stdio.h>\nfopen("/outside/data", "w");'),
    ('.cpp', '#include <cstdio>\nstd::fopen("/outside/data", "r+");'),
    ('.swift', 'import Foundation\nFileManager.default.createFile(atPath: "/outside/data", contents: nil)'),
    ('.m', '#import <Foundation/Foundation.h>\n[[NSFileManager defaultManager] createFileAtPath:@"/outside/data" contents:nil attributes:nil];'),
    ('.dart', "import 'dart:io';\nFile('/outside/data').writeAsStringSync('data');"),
    ('.lua', 'io.open("/outside/data", "w")'),
    ('.pl', 'open(my $fh, ">", "/outside/data");'),
    ('.R', 'writeLines("data", con="/outside/data")'),
    ('.jl', 'open("/outside/data", "w")'),
    ('.ps1', 'Set-Content -LiteralPath "/outside/data" -Value "data"'),
])
def test_write_contracts(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE)
    assert result.blocked, result

@pytest.mark.parametrize('suffix,source', [
    ('.c', '#include <stdio.h>\nfopen("/outside/data", "r");'),
    ('.cpp', '#include <cstdio>\nstd::fopen("/outside/data", "rb");'),
    ('.lua', 'io.open("/outside/data", "r")'),
    ('.lua', 'io.open("/outside/data")'),
    ('.pl', 'open(my $fh, "<", "/outside/data");'),
    ('.jl', 'open("/outside/data", "r")'),
    ('.ps1', 'Remove-Item -LiteralPath "/" -Recurse -WhatIf'),
    ('.ps1', 'Write-Output Remove-Item "/" -Recurse'),
    ('.c', 'void clean() { thing.remove("/outside/data"); }'),
    ('.cpp', 'thing.remove_all("/");'),
    ('.swift', 'fake.removeItem(atPath: "/")'),
    ('.m', '[fake removeItemAtPath:@"/" error:NULL];'),
    ('.dart', "import 'custom.dart';\nDirectory('/').delete(recursive:true);"),
    ('.lua', 'function clean(os) os.remove("/outside/data") end'),
    ('.pl', 'sub remove_tree { return 1; } remove_tree("/");'),
    ('.R', 'unlink <- function(x, recursive) 1; unlink("/", recursive=TRUE)'),
    ('.jl', 'rm(x; recursive=false) = nothing; rm("/"; recursive=true)'),
    ('.ps1', 'function Remove-Item { param($LiteralPath) }; Remove-Item -LiteralPath "/" -Recurse'),
])
def test_non_mutations_and_unknown_identities_do_not_block(suffix, source):
    assert not analyze('cleanup' + suffix, source, WORKSPACE).blocked

@pytest.mark.parametrize('suffix,source', [
    ('.c', '#include <stdio.h>\n/* remove("/outside/data"); */'),
    ('.cpp', '#include <filesystem>\nauto example = R"demo(std::filesystem::remove_all("/"))demo";'),
    ('.swift', 'import Foundation\nlet example = """\nFileManager.default.removeItem(atPath: "/")\n"""'),
    ('.m', '#import <Foundation/Foundation.h>\n// [[NSFileManager defaultManager] removeItemAtPath:@"/" error:NULL];'),
    ('.dart', "import 'dart:io';\nvar example = '''Directory('/').delete(recursive:true);''';"),
    ('.lua', '--[=[os.remove("/outside/data")]=]'),
    ('.lua', 'example = [=[os.remove("/outside/data")]=]'),
    ('.pl', '=pod\nremove_tree("/");\n=cut\n'),
    ('.pl', 'my $example = q{unlink("/outside/data")};'),
    ('.pl', 'my $example = q!unlink("/outside/data")!;'),
    ('.pl', r'my $example = q{\} unlink("/outside/data")};'),
    ('.cpp', '#include <filesystem>\nauto example = u8R"tag(a quote " std::filesystem::remove_all("/"))tag";'),
    ('.R', '# unlink("/", recursive=TRUE)'),
    ('.jl', '#= #= nested =# rm("/"; recursive=true) =#'),
    ('.ps1', "$example = @'\nRemove-Item -LiteralPath '/' -Recurse\n'@"),
    ('.ps1', '<# Remove-Item -LiteralPath "/" -Recurse #>'),
])
def test_comments_and_quoted_examples_are_not_operations(suffix, source):
    assert not analyze('cleanup' + suffix, source, WORKSPACE).blocked


@pytest.mark.parametrize('suffix,source', [
    ('.cpp', '#include <fstream>\nvoid clean() { std::ofstream stream("/outside/data"); }'),
    ('.pl', 'unlink "/outside/data";'),
    ('.pl', 'use File::Path qw(remove_tree);\nremove_tree "/outside/data" if $enabled;'),
    ('.pl', 'unlink("/workspace/owned", "/outside/data");'),
    ('.R', 'file.remove("/workspace/owned", "/outside/data")'),
    ('.jl', 'open("/outside/data"; write=true)'),
    ('.ps1', 'Remove-Item -LiteralPath "/workspace/owned", "/outside/data" -Recurse'),
    ('.ps1', 'REMOVE-ITEM -LITERALPATH "/outside/data" -RECURSE -WHATIF:$false'),
    ('.dart', "import 'dart:io';\nnew Directory('/outside/data').deleteSync(recursive:true);"),
])
def test_additional_real_call_forms(suffix, source):
    assert analyze('cleanup' + suffix, source, WORKSPACE).blocked


@pytest.mark.parametrize('suffix,source', [
    ('.swift', 'import Foundation\ntry FileManager.default.removeItem(at: URL(fileURLWithPath: "/"))'),
    ('.cpp', '#include <filesystem>\nstd::filesystem::remove_all(std::filesystem::path("/"));'),
    ('.R', 'base::unlink(base::dirname("/child"), recursive=TRUE)'),
    ('.jl', 'Base.rm(Base.dirname("/child"); recursive=true)'),
])
def test_closed_path_expressions_use_shared_root_policy(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE, 'write')
    assert result.blocked, result
    assert any(f.confidence == 'PROVEN' and f.rule == 'root' for f in result.findings)


@pytest.mark.parametrize('suffix,source', [
    ('.c', '#include <stdio.h>\nint remove(const char *p) {return 0;} remove("/outside/data");'),
    ('.c', '#include <stdio.h>\n#define remove no_op\nremove("/outside/data");'),
    ('.cpp', '#include <filesystem>\nauto size = sizeof(std::filesystem::remove_all("/"));'),
    ('.cpp', '#include <filesystem>\nusing Size = decltype(std::filesystem::remove_all("/"));'),
    ('.cpp', '#include <fstream>\nother::std::ofstream stream("/outside/data");'),
    ('.swift', 'import Foundation\nclass FileManager {}\nFileManager.default.removeItem(atPath:"/")'),
    ('.dart', "import 'dart:io';\nvoid clean(Directory) { Directory('/').delete(recursive:true); }"),
    ('.dart', "import 'dart:io';\ncustom.Directory('/').delete(recursive:true);"),
    ('.lua', 'os.remove = custom; os.remove("/outside/data")'),
    ('.lua', 'io.open("/outside/data", mode)'),
    ('.pl', 'use File::Path qw(remove_tree);\nsub remove_tree { return 1; } remove_tree("/");'),
    ('.pl', 'my $example = <<\'END_EXAMPLE\';\nunlink("/outside/data");\nEND_EXAMPLE\n'),
    ('.pl', '__DATA__\nunlink("/outside/data");'),
    ('.R', 'quote(unlink("/", recursive=TRUE))'),
    ('.R', 'expression(unlink("/", recursive=TRUE))'),
    ('.jl', 'example = :(rm("/"; recursive=true))'),
    ('.jl', '@custom(rm("/"; recursive=true))'),
    ('.jl', 'example = quote\nrm("/"; recursive=true)\nend'),
    ('.jl', 'open("/outside/data"; write=enabled)'),
    ('.ps1', 'set-alias Remove-Item Write-Output; Remove-Item -Path "/" -Recurse'),
    ('.ps1', 'Write-Output ";" Remove-Item -Path "/" -Recurse'),
    ('.ps1', 'Remove-Item -Path "/" -Recurse -WhatIf:$true'),
    ('.ps1', 'Remove-Item -Path "/" -Recurse -WhatIf:$preview'),
])
def test_ambiguous_identity_unevaluated_code_and_dynamic_modes_stay_nonblocking(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE)
    assert not result.blocked, result


@pytest.mark.parametrize('suffix,source', [
    ('.R', 'quote(unlink("/", recursive=TRUE)); unlink("/", recursive=TRUE)'),
    ('.cpp', '#include <filesystem>\nsizeof(std::filesystem::remove_all("/")); std::filesystem::remove_all("/");'),
    ('.jl', 'example = :(rm("/"; recursive=true)); rm("/"; recursive=true)'),
    ('.jl', '@show(enabled); rm("/"; recursive=true)'),
])
def test_unevaluated_example_does_not_hide_a_separate_real_call(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE, 'write')
    assert result.blocked, result
    assert sum(f.confidence == 'PROVEN' for f in result.findings) == 1


@pytest.mark.parametrize('suffix,source', [
    ('.c', '#include <stdio.h>\nfopen("/outside/data", "r"); /*'),
    ('.lua', 'example = [=[os.remove("/outside/data")'),
    ('.ps1', "$x = @'\nRemove-Item -Path '/' -Recurse"),
])
def test_unterminated_lexical_regions_are_explicitly_unverified(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE)
    assert result.coverage == 'invalid-source'
    assert not result.blocked


@pytest.mark.parametrize('suffix,source', [
    ('.swift', r'import Foundation; FileManager.default.removeItem(atPath:"/\(target)")'),
    ('.dart', 'import "dart:io"; File("/$target").delete();'),
    ('.pl', 'unlink("/$target");'),
    ('.pl', 'unlink("/@targets");'),
    ('.jl', 'rm("/$target"; recursive=true)'),
    ('.ps1', 'Remove-Item -LiteralPath "/$target" -Recurse'),
    ('.ps1', r"Remove-Item -LiteralPath 'C:\' -Recurse"),
])
def test_interpolation_and_windows_targets_are_unknown_not_literal_proofs(suffix, source):
    result = analyze('cleanup' + suffix, source, WORKSPACE)
    assert not result.blocked, result
    assert result.coverage == 'supported-subset'
    assert any(f.confidence == 'UNKNOWN' for f in result.findings), result


def test_token_budget_is_not_a_partial_clean_verdict():
    result = analyze('cleanup.lua', 'x=1\n' * 6000, WORKSPACE)
    assert result.coverage == 'analysis-limit'


@pytest.mark.parametrize('suffix', ['.c', '.cpp', '.swift', '.m', '.dart', '.lua', '.pl', '.R', '.jl', '.ps1'])
def test_quoted_punctuation_is_not_parser_structure(suffix):
    # A literal ')' must not close an enclosing call or expose its contents.
    assert not analyze('example' + suffix, 'example(")", "/outside/data")', WORKSPACE).blocked


@pytest.mark.parametrize('language,suffix,prelude,operation', CASES)
@pytest.mark.parametrize('tool', ['write_file', 'edit_file'])
def test_real_lowering_refuses_each_adapter_without_executing_source(language, suffix, prelude, operation, tool):
    path = 'cleanup' + suffix
    previous = prelude + operation.replace('/outside/data', '/workspace/scratch')
    candidate = prelude + operation
    payload = {'path': path, 'content': candidate} if tool == 'write_file' else {
        'path': path, 'old_string': '/workspace/scratch', 'new_string': '/outside/data'}
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'one', 'type': 'function', 'function': {
        'name': tool, 'arguments': json.dumps(payload)}}]}}]}
    view = writeproxy.wsview.View(WORKSPACE)
    view.note_read(path, previous)
    log = Mock()
    with patch.object(writeproxy.wsview, 'current', return_value=view):
        writeproxy.translate_outbound(completion, {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}},
                                      injected={tool}, workspace_root=WORKSPACE, external_dir_permission='none', rlog=log)
    cmd = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert 'withheld' in cmd
    assert writeproxy._write_command(path, candidate) not in cmd
    assert writeproxy._edit_command(path, '/workspace/scratch', '/outside/data') not in cmd
    assert any(c.args[0] == 'safety.cleanup_review' and c.kwargs['verdict'] == 'UNSAFE' for c in log.emit.call_args_list)
