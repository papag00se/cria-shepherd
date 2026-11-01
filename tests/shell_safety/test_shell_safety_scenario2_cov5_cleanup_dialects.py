"""Scenario: scripts a coder writes in the less common languages (C++, Perl, Lua, Julia, Dart, Objective-C, R, Elixir, PowerShell) are read for the deletion/overwrite
of an external path: a resolved, identity-certain call is PROVEN and blocked, dynamic code or an unknown identity is UNKNOWN (never a refusal), a read-only open or a quoted
expression is nothing, and source that cannot be lexed is skipped as invalid - strings only, nothing is executed."""
import pytest

from cria.cleanupsafety import analyze

PROVEN = {('PROVEN', 'external')}
UNRESOLVED = {('UNKNOWN', 'unresolved')}
WITHIN = {('WITHIN_SCOPE', 'within')}


@pytest.mark.parametrize("path, source, blocked, findings", [
    ("f.cpp", '#include <filesystem>\nint main(){ std::filesystem::remove_all("/external"); }', True, PROVEN),
    ("f.cpp", '#include <fstream>\nint main(){ std::ofstream out("/external/f"); }', True, PROVEN),
    ("f.cpp", 'auto s = R"x(abc)x"; std::filesystem::remove_all("/");', False, UNRESOLVED),            # a raw string lexes; no include, so the identity is unproven
    ("f.cpp", 'auto s = R"x(abc', False, set()), ("f.cpp", 'auto s = R"bad', False, set()),             # unterminated / malformed raw strings: not source
    ("f.pl", 'use File::Path qw(remove_tree);\nremove_tree("/external");', True, PROVEN),
    ("f.pl", 'use File::Path;\nFile::Path::remove_tree("/external");', True, PROVEN),
    ("f.pl", 'open(my $fh, ">", "/external/f");', True, PROVEN),
    ("f.pl", 'unlink("/external/f");\neval $x;', False, UNRESOLVED),                                    # eval anywhere: nothing can be certified
    ("f.lua", 'os.remove("/external/f")', True, PROVEN), ("f.lua", 'io.open("/external/f", "w")', True, PROVEN),
    ("f.lua", 'load("x"); os.remove("/external/f")', False, UNRESOLVED),
    ("f.lua", 'io.open("/external/f")', False, set()), ("f.lua", 'io.open("/external/f", "r")', False, set()),   # opening to read destroys nothing
    ("f.jl", 'rm("/external/f")', True, PROVEN), ("f.jl", 'rm("/external/f", recursive=true)', True, PROVEN),
    ("f.jl", 'quote\nrm("/external")\nend', False, UNRESOLVED), ("f.jl", 'x = :(rm("/external"))', False, set()),   # quoted code is data, a quote block is unprovable
    ("f.dart", 'import "dart:io";\nvoid main(){ File("/external/f").deleteSync(); }', True, PROVEN),
    ("f.dart", 'import "dart:io";\nvoid main(){ Directory("/external").deleteSync(recursive: true); }', True, PROVEN),
    ("f.dart", 'import "dart:io";\nvoid main(){ File("/external/f").writeAsStringSync("x"); }', True, PROVEN),
    ("f.m", '#import <Foundation/Foundation.h>\nint main(){ [[NSFileManager defaultManager] removeItemAtPath:@"/external" error:nil]; }', True, PROVEN),
    ("f.m", '[[NSFileManager defaultManager] removeItemAtPath:@"/external" error:nil];', False, UNRESOLVED),   # Foundation never imported: identity unknown
    ("f.r", 'unlink("/external/f")', True, PROVEN), ("f.r", 'file.remove("/external/f"); eval(x)', False, UNRESOLVED),
    ("f.ex", 'File.rm_rf("/external")', True, PROVEN),
    ("f.ps1", 'Remove-Item "/external"; Invoke-Expression $x', False, UNRESOLVED),
    ("f.ps1", '$p = @"\nunterminated', False, set()),                                                     # an unterminated here-string is not source
    ("f.ps1", "$x = @'\nhere\n'@\nRemove-Item -Recurse \"/external\"", False, UNRESOLVED),
    ("f.lua", 'os.remove("/project/build/f")', False, WITHIN),                                           # control: a project path is within scope in any dialect
    ("f.pl", 'unlink("/project/build/f");', False, WITHIN),
    ("f.r", 'unlink(file.path("/external","x"))', True, PROVEN), ("f.r", 'base::unlink(dirname("/external/a/b"))', True, PROVEN),   # path helpers are followed
    ("f.r", 'unlink(file.path(x,"y"))', False, UNRESOLVED), ("f.r", 'unlink(dirname("/external/a","b"))', False, UNRESOLVED),    # a variable part / wrong arity: no proof
    ("f.r", 'writeLines("x", "/external/f")', True, PROVEN), ("f.r", 'unlink(("/external/f"))', True, PROVEN),
    ("f.jl", 'rm(joinpath("/external","a"))', True, PROVEN), ("f.jl", 'rm(dirname("/external/a/b"))', True, PROVEN),
    ("f.jl", 'open("/external/f", "w")', True, PROVEN), ("f.jl", 'write("/external/f", "x")', True, PROVEN), ("f.jl", 'open("/external/f")', False, set()),
    ("f.cpp", '#include <filesystem>\nint main(){ std::filesystem::remove_all(std::filesystem::path("/external")); }', True, PROVEN),
    ("f.cpp", '#include <filesystem>\nint main(){ std::filesystem::remove_all(std::filesystem::path("/a","/b")); }', False, UNRESOLVED),
    ("f.cpp", '#include <cstdio>\nint main(){ std::remove("/external/f"); }', True, PROVEN),
    ("f.cpp", '#include <cstdio>\nint main(){ std::fopen("/external/f","w"); }', True, PROVEN), ("f.cpp", '#include <cstdio>\nint main(){ std::fopen("/external/f","r"); }', False, set()),
    ("f.c", '#include <unistd.h>\nint main(){ unlink("/external/f"); }', True, PROVEN),
    ("f.c", '#include <stdio.h>\nint main(){ fopen("/external/f","w"); remove("/external/g"); }', True, PROVEN),
    ("f.swift", 'import Foundation\nFileManager.default.removeItem(atPath: "/external")', True, PROVEN),
    ("f.swift", 'import Foundation\nFileManager.default.removeItem(at: URL(fileURLWithPath: "/external"))', True, PROVEN),
    ("f.swift", 'import Foundation\nFileManager.default.createFile(atPath: "/external/f", contents: nil)', True, PROVEN),
    ("f.swift", 'FileManager.default.removeItem(atPath: "/external")', False, UNRESOLVED),                 # Foundation not imported
    ("f.swift", 'FileManager.default.removeItem(atPath: "/external")\nimport Foundation', True, PROVEN),   # imports are order-free: one as the very last token still counts
    ("f.swift", 'FileManager.default.removeItem(atPath: "/external")\nimport', False, UNRESOLVED),        # a bare trailing `import` names nothing (and must not read past the tokens)
    ("f.swift", 'let s = "import"\nFoundation\nFileManager.default.removeItem(atPath: "/external")', False, UNRESOLVED),   # a string saying "import" is not an import
    ("f.lua", 'local f = io.open("/external/f", "a")', True, PROVEN), ("f.pl", 'open(FH, ">>", "/external/f");', True, PROVEN),
    ("f.pl", 'rmdir("/external"); CORE::unlink("/external/g");', True, PROVEN),
    ("f.dart", 'void main(){ File("/external/f").deleteSync(); }', False, UNRESOLVED),                    # dart:io never imported
    ("f.dart", 'import "dart:io";\nvoid main(){ File("/project/f").deleteSync(); }', False, WITHIN),
    ("f.r", 'unlink(' + '(' * 70 + '"/external/f"' + ')' * 70 + ')', False, set()),                          # nesting past the expression budget: the analysis stops, it does not guess
    ("f.r", 'unlink(' + '(' * 20 + '"/external/f"' + ')' * 20 + ')', True, PROVEN),                           # control: the same shape within the budget is proven
])
def test_less_common_languages_are_proven_only_with_a_certain_identity_and_an_external_target(path, source, blocked, findings):
    result = analyze(path, source, '/project')
    assert result.blocked is blocked and {(f.confidence, f.rule) for f in result.findings} == findings
