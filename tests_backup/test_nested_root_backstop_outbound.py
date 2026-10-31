"""Harmless Bash oracle; root deletion shapes are classified, never executed."""
import json,subprocess
import pytest
from cria import assistruntime,dirguard,writeproxy
BS=chr(92)
ACTIVE=[
 'echo "$'+BS+'\n(@X@)"',
 'echo "$(echo "a # b")"; @X@',
 'echo "$(echo a # it\'s\n@X@)"',
 'echo "$(echo a # ) it\'s\n@X@)"',
 'echo `echo '+BS+'$(@X@)`',
 'echo "`echo '+BS+'`@X@'+BS+'``"',
 'echo hi; "$(true)"@X@',
 'echo "$(printf \'%s\' "$(echo \'a)\'; @X@)")"',
 'cat <(echo "$(echo a # it\'s\n@X@)")',
 'cat <(echo "$'+BS+'\n(@X@)")',
]
LITERAL=[
 "echo '$(@X@)'",
 'echo "'+BS+'$(@X@)"',
 'echo ok # `@X@`',
 'echo "<( @X@ ) >( @X@ )"',
 "printf '%s' $'literal\\\'$( @X@ )'",
 'echo "$(printf \'%s\' \'$(@X@)\')"',
]

def forwarded(command,root,level):
 comp={'choices':[{'message':{'tool_calls':[{'id':'nested','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':command})}}]}}]}
 tool={'type':'function','name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}},'required':['cmd']}}
 with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
  writeproxy.translate_outbound(comp,tool,injected={'read_file','write_file','edit_file','list_dir'},workspace_root=str(root),external_dir_permission=level)
 return writeproxy._command_of(comp['choices'][0]['message']['tool_calls'][0]['function']['arguments'])

@pytest.mark.parametrize('template',ACTIVE)
@pytest.mark.parametrize('level',['none','read','write'])
def test_bash_reaches_harmless_oracle_and_actual_policy_refuses_root_shape(template,level,tmp_path):
 oracle=template.replace('@X@','touch ran.flag')
 result=subprocess.run(['bash','--norc','--noprofile','-c',oracle],cwd=tmp_path,capture_output=True,timeout=10)
 assert (tmp_path/'ran.flag').exists(),result.stderr
 command=template.replace('@X@','rm -rf /')
 assert dirguard.root_recursive_delete_refusal(command) is not None,command
 assert forwarded(command,tmp_path,level)!=command
 assert dirguard.command_refusal(command,level,str(tmp_path)) is not None

@pytest.mark.parametrize('template',LITERAL)
@pytest.mark.parametrize('level',['none','read','write'])
def test_literal_oracle_stays_inert_and_root_text_is_not_false_refused(template,level,tmp_path):
 subprocess.run(['bash','--norc','--noprofile','-c',template.replace('@X@','touch ran.flag')],cwd=tmp_path,capture_output=True,check=True,timeout=10)
 assert not (tmp_path/'ran.flag').exists()
 command=template.replace('@X@','rm -rf /')
 assert dirguard.root_recursive_delete_refusal(command) is None,command
 assert forwarded(command,tmp_path,level)==command

@pytest.mark.parametrize('command',['echo "$(rm -rf /', 'cat <<EOF\n$(rm -rf /)\nEOF'])
def test_original_unbalanced_and_heredoc_root_abstention_remains(command):
 assert dirguard.root_recursive_delete_refusal(command) is None

@pytest.mark.parametrize('level',['none','read','write'])
def test_split_opener_actual_outbound_boundary_never_forwards_the_root_command(level,tmp_path):
 command='echo "$'+BS+'\n(rm -rf /)"'
 lowered=forwarded(command,tmp_path,level)
 print(json.dumps({'level':level,'forwarded_unchanged':lowered==command,'command':command}))
 assert lowered!=command
