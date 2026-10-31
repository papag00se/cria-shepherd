"""cleanupsafety.analyze: inert review of candidate source, never executing it. Evidence quality, not a parser —
PROVEN only for a represented target violating a supported rule; control flow and unknown languages stay POSSIBLE/UNKNOWN."""
from cria.cleanupsafety import analyze, review

WS = "/workspace"
EXTERNAL = [   # a known external mutation per ecosystem resolves to an `external` finding
    ("f.js", 'const fs = require("fs");\nconst target = "/external/file";\nfs.unlinkSync(target);'),
    ("f.go", 'package main\nimport "os"\nfunc main() { os.RemoveAll("/external") }'), ("f.rs", 'fn main() { std::fs::remove_dir_all("/external"); }'),
    ("F.java", 'import java.nio.file.Files;\nimport java.nio.file.Path;\nclass F { void f() { Files.delete(Path.of("/external/file")); }}'),
    ("f.php", '<?php\n$p = "/external/file";\nunlink($p);'), ("f.rb", 'require "fileutils"\nFileUtils.rm_rf "/external"'),
    ("f.py", 'import shutil\nshutil.rmtree("/external")'),
]
BLOCKED = [   # the shared parent-of-a-temp-path rule and root deletion apply outside Python
    ("f.rb", 'require "fileutils"\nrequire "tmpdir"\nd=Dir.mktmpdir()\nFileUtils.rm_rf(File.dirname(d))'),
    ("f.sh", "#!/bin/bash\nrm -rf /"), ("f.sh", "echo ok\nrm -?f --no-preserve-root /"),
]
NOT_BLOCKED = [   # project paths, text, dynamic targets and shapes the lexical adapter cannot certify
    ("f.js", 'const fs=require("fs"); fs.unlinkSync("/workspace/owned");'), ("f.js", 'const fs=require("fs"); let p="/external"; p+=value; fs.unlinkSync(p);'),
    ("f.php", '<?php return; unlink("/external");'),
    ("f.rs", 'fn main() { println!("std::fs::remove_dir_all(\\"/\\")"); }'), ("f.java", '// Files.delete(Path.of("/external"));'),
    ("f.cs", 'someObject.Delete("/external");'), ("f.py", 'import shutil\nshutil.rmtree("/workspace/build")'),
    ("f.sh", 'echo "never rm -rf / on a host"'), ("f.sh", "cat <<'EOF'\nrm -rf /\nEOF"), ("f.sh", "rm -rf build"),
]


def test_each_ecosystems_known_external_mutation_is_found_and_shared_rules_apply_outside_python():
    assert not [p for p, s in EXTERNAL if not any(f.rule == "external" and f.confidence in ("PROVEN", "POSSIBLE") for f in analyze(p, s, WS).findings)]
    assert not [(p, s) for p, s in BLOCKED if not analyze(p, s, WS, "none").blocked]
    assert analyze("f.js", 'const fs=require("fs"); fs.rmSync("/", {recursive:true, force:true});', WS, "write").blocked


def test_project_paths_text_dynamic_targets_and_unknown_languages_never_block():
    assert not [(p, s) for p, s in NOT_BLOCKED if analyze(p, s, WS, "none").blocked]
    assert not analyze("f.js", 'const fs=require("fs"); fs.rmSync("/", {message:"recursive:true"});', WS, "write").blocked   # text, not the option
    unknown = analyze("f.unrecognized", 'thing.deleteTree("/external")', WS)
    assert unknown.coverage == "universal-lexical-only" and unknown.findings[0].confidence == "UNKNOWN" and not unknown.blocked
    branch = analyze("f.js", 'const fs=require("fs"); if (condition) { fs.unlinkSync("/external"); }', WS)
    assert not branch.blocked and any(f.confidence == "POSSIBLE" for f in branch.findings)       # control flow is not certified


def test_review_refuses_with_evidence_only_when_proven_and_stays_silent_for_unchanged_or_clean_source():
    proven = review("f.sh", "rm -rf /", None, WS, permission="write")
    assert proven and "rm -rf /" in proven and "cria" not in proven.lower()
    assert review("f.sh", "rm -?f --no-preserve-root /", None, WS, permission="write")       # POSSIBLE still refuses, without evidence
    assert review("f.sh", "rm -rf /", "rm -rf /", WS) is None and review("f.sh", "ls", None, WS) is None
