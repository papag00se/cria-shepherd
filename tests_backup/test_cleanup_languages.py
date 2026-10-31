"""API contracts raise evidence quality, never pretend to parse whole languages."""
import pytest
from cria.cleanupsafety import analyze


@pytest.mark.parametrize('path,source', [
    ('f.js', 'const fs = require("fs");\nconst target = "/external/file";\nfs.unlinkSync(target);'),
    ('f.ts', 'import fs from "node:fs";\nfs.writeFileSync("/external/file", "data");'),
    ('f.go', 'package main\nimport "os"\nfunc main() { os.RemoveAll("/external") }'),
    ('f.rs', 'fn main() { std::fs::remove_dir_all("/external"); }'),
    ('F.java', 'import java.nio.file.Files;\nimport java.nio.file.Path;\nclass F { void f() { Files.delete(Path.of("/external/file")); }}'),
    ('f.kt', 'import kotlin.io.path.deleteRecursively\nimport kotlin.io.path.Path\nfun f() {\nval p=Path("/external"); p.deleteRecursively()\n}'),
    ('F.cs', 'using System.IO;\nFile.Delete("/external/file");'),
    ('f.php', '<?php\n$p = "/external/file";\nunlink($p);'),
    ('f.rb', 'require "fileutils"\nFileUtils.rm_rf "/external"'),
    ('f.exs', 'File.rm_rf! "/external"'),
])
def test_each_ecosystem_resolves_a_known_external_mutation(path, source):
    report=analyze(path,source,'/workspace')
    assert report.coverage == 'supported-subset'
    assert any(f.confidence in ('PROVEN','POSSIBLE') and f.rule=='external' for f in report.findings), report


@pytest.mark.parametrize('path,source', [
    ('f.js','const fs=require("fs");\nconst path=require("path");\nlet p="/external/file";\nfs.unlinkSync(path.join(path.dirname(p),"other"));'),
    ('f.rb','require "fileutils"\nrequire "tmpdir"\nd=Dir.mktmpdir()\nFileUtils.rm_rf(File.dirname(d))'),
    ('f.cs','using System.IO;\nvar p=Path.GetTempFileName();\nDirectory.Delete(Path.GetDirectoryName(p),true);'),
])
def test_shared_path_and_resource_rules_apply_outside_python(path,source):
    report=analyze(path,source,'/workspace')
    assert report.blocked, report


@pytest.mark.parametrize('path,source', [
    ('f.js','const fs=require("fs"); fs.unlinkSync("/workspace/owned");'),
    ('f.js','const fs=require("fs"); fs=custom; fs.unlinkSync("/external");'),
    ('f.js','const fs=require("fs"); fs.unlinkSync=custom; fs.unlinkSync("/external");'),
    ('f.js','const fs=require("fs"); let p="/external"; p+=value; fs.unlinkSync(p);'),
    ('f.js','const fs=require("fs"); let p="/external"; [p]=items; fs.unlinkSync(p);'),
    ('f.php','<?php return; unlink("/external");'),
    ('f.rs','fn main() { println!("std::fs::remove_dir_all(\"/\")"); }'),
    ('f.java','// Files.delete(Path.of("/external"));'),
    ('f.php','<?php $p="/$dynamic"; unlink($p);'),
    ('f.rb','# FileUtils.rm_rf "/external"'),
    ('f.exs','File.rm_rf!("/#{dynamic}")'),
    ('f.cs','someObject.Delete("/external");'),
])
def test_safe_inert_dynamic_and_lookalike_calls_do_not_block(path,source):
    assert not analyze(path,source,'/workspace').blocked


def test_shell_source_reuses_direct_root_backstop_without_execution():
    assert analyze('f.sh', '#!/bin/bash\nrm -rf /', '/workspace').blocked
    assert not analyze('f.sh', 'echo "never rm -rf / on a host"', '/workspace').blocked
    assert not analyze('f.sh', "cat <<'EOF'\nrm -rf /\nEOF", '/workspace').blocked


def test_universal_scan_is_advisory_even_for_dangerous_looking_literals():
    report=analyze('f.unrecognized', 'thing.deleteTree("/external")', '/workspace')
    assert report.coverage == 'universal-lexical-only'
    assert not report.blocked
    assert report.findings[0].confidence == 'UNKNOWN'


def test_node_recursive_options_are_data_not_an_unknown_control_scope():
    report=analyze('f.js', 'const fs=require("fs"); fs.rmSync("/", {recursive:true, force:true});', '/workspace', 'write')
    assert report.blocked


def test_recursive_option_requires_a_boolean_value_not_text_mention():
    report=analyze('f.js', 'const fs=require("fs"); fs.rmSync("/", {message:"recursive:true"});', '/workspace', 'write')
    assert not report.blocked


def test_control_flow_is_not_certified_by_lexical_adapter():
    report=analyze('f.js','const fs=require("fs"); if (condition) { fs.unlinkSync("/external"); }', '/workspace')
    assert not report.blocked
    assert any(f.confidence=='POSSIBLE' for f in report.findings)
