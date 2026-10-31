"""Root-target regressions are inert source strings, never executed or imported."""
import json
from unittest.mock import Mock, patch
import pytest
from cria.cleanupsafety import analyze
from cria import writeproxy

JS = 'const fs=require("fs");\n'
DELETE = 'fs.rmSync("/", {recursive:true});'


@pytest.mark.parametrize('wrapper', [
    'function cleanup() { CALL }', 'if (cleanupNeeded) { CALL }',
    'function cleanup() { if (cleanupNeeded) { CALL } }',
    'const cleanup = () => { CALL };',
])
def test_root_target_is_not_weakened_by_execution_control(wrapper):
    source=JS+wrapper.replace('CALL', DELETE)
    result=analyze('f.js', source, '/workspace', 'write')
    assert result.blocked, result
    assert any(f.confidence=='PROVEN' and f.rule=='root' for f in result.findings)


@pytest.mark.parametrize('path,source', [
    ('f.ts', 'import fs from "node:fs"; function cleanup() { if (enabled) { fs.rmSync("/", {recursive:true}); }}'),
    ('F.java', 'import org.apache.commons.io.FileUtils; import java.io.File; class F { void cleanup() { if (enabled) { FileUtils.deleteDirectory(new File("/")); } }}'),
    ('f.js', 'function cleanup() { const fs=require("fs"); if (enabled) { '+DELETE+' }}'),
    ('f.js', 'import * as disk from "node:fs"; function cleanup() { disk.rmSync("/",{recursive:true}); }'),
    ('f.go', 'package main\nimport "os"\nfunc cleanup() { if enabled { os.RemoveAll("/") } }'),
    ('f.rs', 'fn cleanup() { if enabled { std::fs::remove_dir_all("/"); }}'),
    ('f.cs', 'using System.IO; class C { void Cleanup() { if (enabled) { Directory.Delete("/",true); } }}'),
    ('f.rb', 'require "fileutils"\ndef cleanup\n if enabled\n  FileUtils.rm_rf("/")\n end\nend'),
    ('f.exs', 'defmodule Cleanup do\n def run do\n  if enabled do\n   File.rm_rf!("/")\n  end\n end\nend'),
    ('f.py', 'import shutil\ndef cleanup():\n if enabled:\n  shutil.rmtree("/")'),
    ('f.js', JS+'const path=require("path"); function cleanup() { fs.rmSync(path.dirname("/child"), {recursive:true}); }'),
])
def test_known_api_and_closed_root_expression_survive_wrappers(path,source):
    assert analyze(path,source,'/workspace','write').blocked


@pytest.mark.parametrize('source', [
    JS+'function cleanup(fs) { '+DELETE+' }',
    JS+'with (custom) { '+DELETE+' }',
    'let fs=require("fs"); eval(code); function cleanup() { '+DELETE+' }',
    'function setup() { const fs=require("fs"); } function cleanup() { '+DELETE+' }',
    JS+'const path=require("path"); function cleanup(path) { fs.rmSync(path.dirname("/child"),{recursive:true}); }',
    JS+'const cleanup = (fs) => { '+DELETE+' };',
    'function cleanup(fs=require("fs")) { '+DELETE+' }',
    JS+'const cleanup = (fs=require("fs")) => { '+DELETE+' };',
    JS+'function cleanup() { const fs=custom; '+DELETE+' }',
    JS+'function cleanup() { fs.rmSync=custom; '+DELETE+' }',
    JS+'function cleanup() { fs.rmSync(target, {recursive:true}); }',
    JS+'function cleanup(target) { if (enabled) target="/"; fs.rmSync(target,{recursive:true}); }',
    JS+'function cleanup() { let target="/workspace/scratch"; if (enabled) target="/"; fs.rmSync(target,{recursive:true}); }',
    JS+'function cleanup() { fs.rmSync("/workspace/scratch",{recursive:true}); }',
    'function cleanup(fs) { '+DELETE+' }',
    JS+'// function cleanup() { '+DELETE+' }',
    JS+'''const example = 'function cleanup() { fs.rmSync("/", {recursive:true}); }';''',
    JS+'function cleanup() { fs.rmSync("/",{recursive:flag}); }',
    JS+'function cleanup() { fs.rmSync("/",{recursive:false}); }',
    JS+'function cleanup() { '+DELETE+' } fs=custom;',
    'function require(name) { return custom; } '+JS+'function cleanup() { '+DELETE+' }',
])
def test_unresolved_identities_targets_and_inert_text_are_not_promoted(source):
    assert not analyze('f.js',source,'/workspace','write').blocked


def test_macro_tokens_are_not_assumed_to_execute_but_unrelated_macros_do_not_weaken_calls():
    assert not analyze('f.rs', 'fn example() { stringify!(std::fs::remove_dir_all("/")); }', '/workspace','write').blocked
    assert analyze('f.rs', 'fn cleanup() { println!("cleanup"); std::fs::remove_dir_all("/"); }', '/workspace','write').blocked


def test_root_call_without_recursive_option_still_obeys_external_write_policy():
    source=JS+'function cleanup() { if (enabled) fs.rmSync("/"); }'
    assert analyze('f.js',source,'/workspace','none').blocked
    assert not analyze('f.js',source,'/workspace','write').blocked


def test_production_edit_lowering_refuses_wrapped_root_operation():
    previous=JS+'function cleanup() { if (enabled) { /* cleanup */ }}'
    completion={'choices':[{'message':{'tool_calls':[{'id':'one','type':'function','function':{
        'name':'edit_file','arguments':json.dumps({'path':'cleanup.js','old_string':'/* cleanup */','new_string':DELETE})}}]}}]}
    view=writeproxy.wsview.View('/workspace')
    view.note_read('cleanup.js', previous)
    with patch.object(writeproxy.wsview, 'current', return_value=view):
        writeproxy.translate_outbound(completion, {'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}},
                                      injected={'edit_file'},workspace_root='/workspace',external_dir_permission='write')
    cmd=json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert writeproxy._edit_command('cleanup.js','/* cleanup */',DELETE) not in cmd
    assert 'withheld' in cmd


def test_production_write_lowering_refuses_wrapped_root_operation():
    source=JS+'function cleanup() { if (enabled) { '+DELETE+' }}'
    completion={'choices':[{'message':{'tool_calls':[{'id':'one','type':'function','function':{
        'name':'write_file','arguments':json.dumps({'path':'cleanup.js','content':source})}}]}}]}
    log=Mock()
    writeproxy.translate_outbound(completion, {'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}},
                                  injected={'write_file'},workspace_root='/workspace',external_dir_permission='write',rlog=log)
    cmd=json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert writeproxy._write_command('cleanup.js',source) not in cmd
    assert 'withheld' in cmd
    assert any(c.args[0]=='safety.cleanup_review' and c.kwargs['verdict']=='UNSAFE' for c in log.emit.call_args_list)
