"""Cleanup analysis (never run) on source whose LEXING is awkward: substitution/transliteration and raw-string spellings, unterminated
strings and POD, here-strings and WhatIf in PowerShell, Dart method forms, receiver identity in Objective-C/Lua/C++ namespaces, and
R/Julia argument spellings. A literal external mutation blocks; anything the lexer cannot prove is UNKNOWN or invalid, never a block."""
import pytest

from cria.cleanupsafety import analyze

WS = "/workspace"
OUT = '"/outside/data"'
DART = "import 'dart:io';\n"
FOUNDATION = "#import <Foundation/Foundation.h>\n"
# (suffix, source, blocked, coverage, the finding's confidence when there is exactly one)
ROWS = [
    (".pl", '=pod\nunlink("/outside/data");', False, "invalid-source", None), (".pl", 'my $x = s/a/b/; unlink("/outside/data");', False, "supported-subset", "UNKNOWN"),
    (".pl", '$x =~ tr/a-z/A-Z/; unlink("/outside/data");', False, "supported-subset", "UNKNOWN"), (".pl", '$x =~ y/a/b/; unlink("/outside/data");', False, "supported-subset", "UNKNOWN"),
    (".R", 'x <- r"(abc)"; unlink("/outside/data", recursive=TRUE)', False, "supported-subset", "UNKNOWN"),
    (".R", 'x <- R"--[abc]--"; unlink("/outside/data", recursive=TRUE)', False, "supported-subset", "UNKNOWN"),
    (".R", 'x <- r"abc"; unlink("/outside/data", recursive=TRUE)', False, "supported-subset", "UNKNOWN"),
    (".R", 'x <- r"(abc; unlink("/outside/data", recursive=TRUE)', False, "invalid-source", None),
    (".R", 'unlink("/outside/data")', True, "supported-subset", "PROVEN"), (".R", 'unlink("/outside/data", recursive=FALSE)', True, "supported-subset", "PROVEN"),
    (".R", 'unlink("/outside/data", FALSE, TRUE)', True, "supported-subset", "PROVEN"),
    (".ps1", '$x = "a`"b"; Remove-Item -LiteralPath "/outside/data" -Recurse', True, "supported-subset", "PROVEN"),
    (".ps1", '$x = "abc; Remove-Item -LiteralPath "/outside/data" -Recurse', False, "invalid-source", None),
    (".ps1", '$x = @"\nabc\n"@; Remove-Item -LiteralPath "/outside/data" -Recurse', True, "supported-subset", "PROVEN"),
    (".ps1", 'Remove-Item -LiteralPath "/outside/data" -Recurse -WhatIf', False, "supported-subset", None),
    (".ps1", 'Remove-Item -LiteralPath "/outside/data" -WhatIf:$true', False, "supported-subset", None),
    (".ps1", 'Remove-Item -LiteralPath "/outside/data" -Recurse -WhatIf:$false', True, "supported-subset", "PROVEN"),
    (".ps1", 'Remove-Item "/outside/data" -Recurse', True, "supported-subset", "PROVEN"),
    (".ps1", 'Remove-Item -Path "/workspace/a" "/outside/data" -Recurse', False, "supported-subset", "UNKNOWN"),
    (".dart", DART + "var s = r'a'; Directory('/outside/data').deleteSync(recursive: true);", True, "supported-subset", "PROVEN"),
    (".dart", DART + "File('/outside/data').delete();", True, "supported-subset", "PROVEN"), (".dart", DART + "File('/outside/data').writeAsString('x');", True, "supported-subset", "PROVEN"),
    (".dart", DART + "File('/outside/data').readAsStringSync();", False, "supported-subset", None),
    (".dart", DART + "var f = File('/outside/data'); f.deleteSync();", False, "supported-subset", "UNKNOWN"),
    (".c", "#include <stdio.h>\nchar c = '/'; remove(" + OUT + ");", True, "supported-subset", "PROVEN"),
    (".c", "#include <stdio.h>\nchar c = '\\\\'; remove(" + OUT + ");", True, "supported-subset", "PROVEN"),
    (".jl", 'rm("/outside/data"; recursive=false)', True, "supported-subset", "PROVEN"), (".jl", 'rm("/outside/data"; force=true)', True, "supported-subset", "PROVEN"),
    (".jl", 'x = a\'; rm("/outside/data"; recursive=true)', False, "invalid-source", None),
    (".m", FOUNDATION + "[[NSFileManager defaultManager] removeItemAtPath:path error:NULL];", False, "supported-subset", "UNKNOWN"),
    (".m", FOUNDATION + '[[NSFileManager defaultManager] fileExistsAtPath:@"/outside/data"];', False, "supported-subset", None),
    (".m", FOUNDATION + '[fm removeItemAtPath:@"/outside/data" error:NULL];', False, "supported-subset", None),
    (".m", FOUNDATION + '[[NSFileManager alloc] removeItemAtPath:@"/outside/data" error:NULL];', False, "supported-subset", "UNKNOWN"),
    (".swift", 'import Foundation\nfunc f() { FileManager.default.removeItem(atPath: "/outside/data") }', True, "supported-subset", "PROVEN"),
    (".lua", 'local os = {}; os.remove("/outside/data")', False, "supported-subset", "UNKNOWN"), (".lua", 'local f = io.open("/outside/data", "r")', False, "supported-subset", None),
    (".lua", "x = ' unterminated\nos.remove('/outside/data')", False, "invalid-source", None),
    (".cpp", '#include <filesystem>\nnamespace fs = std::filesystem; fs::remove_all("/outside/data");', False, "supported-subset", "UNKNOWN"),
    (".cpp", '#include <filesystem>\nusing namespace std::filesystem; remove_all("/outside/data");', False, "supported-subset", "UNKNOWN"),
]


@pytest.mark.parametrize("suffix,source,blocked,coverage,confidence", ROWS)
def test_awkward_lexing_blocks_only_what_it_can_prove_and_says_unknown_or_invalid_otherwise(suffix, source, blocked, coverage, confidence):
    result = analyze("cleanup" + suffix, source, WS)
    assert result.blocked is blocked and result.coverage == coverage
    assert [f.confidence for f in result.findings] == ([confidence] if confidence else [])
    assert not analyze("cleanup" + suffix, source, WS, "write").blocked          # `write` permission lifts the external rule (none of these deletes the root)
