"""Shared lexical adapter for non-Python source, with explicit API contracts.

This is NOT a compiler. Control flow lowers confidence in the flat variable map,
not in a closed root-target expression with a stable API binding. Such root calls
remain PROVEN inside functions/conditionals. Shadowing, rebinding, computed dispatch
and unsupported target expressions remain uncertain.
The universal mode supplies UNKNOWN leads only; no lexical match alone blocks.
"""
from dataclasses import dataclass
import json
import re

from .cleanupfacts import Analysis, Finding, PathFact, classify, parent_fact, join_fact, is_root

LANGUAGES = {
    '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript', '.jsx': 'javascript',
    '.ts': 'typescript', '.tsx': 'typescript', '.go': 'go', '.rs': 'rust',
    '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin', '.cs': 'csharp',
    '.php': 'php', '.rb': 'ruby', '.ex': 'elixir', '.exs': 'elixir',
    '.sh': 'shell', '.bash': 'shell',
}

# Mutation contracts: qualified API -> recursive flag. No arbitrary method-name equivalence.
APIS = {
    'javascript': {'fs.rmSync': True, 'fs.rm': True, 'fs.rmdirSync': True, 'fs.rmdir': True,
                   'fs.unlinkSync': False, 'fs.unlink': False, 'fs.writeFileSync': False,
                   'fs.writeFile': False, 'fs.truncateSync': False, 'fs.truncate': False},
    'go': {'os.RemoveAll': True, 'os.Remove': False, 'os.WriteFile': False, 'os.Truncate': False},
    'rust': {'std::fs::remove_dir_all': True, 'std::fs::remove_file': False,
             'std::fs::write': False, 'std::fs::File::create': False},
    'java': {'java.nio.file.Files.delete': False, 'java.nio.file.Files.deleteIfExists': False,
             'java.nio.file.Files.write': False, 'java.nio.file.Files.writeString': False,
             'org.apache.commons.io.FileUtils.deleteDirectory': True},
    'kotlin': {'kotlin.io.path.deleteRecursively': True},
    'csharp': {'System.IO.Directory.Delete': True, 'System.IO.File.Delete': False,
               'System.IO.File.WriteAllText': False, 'System.IO.File.WriteAllBytes': False},
    'php': {'unlink': False, 'rmdir': False, 'file_put_contents': False},
    'ruby': {'FileUtils.rm_rf': True, 'FileUtils.remove_entry': True, 'File.delete': False,
             'File.unlink': False, 'File.write': False, 'File.truncate': False, 'Dir.rmdir': False},
    'elixir': {'File.rm_rf': True, 'File.rm_rf!': True, 'File.rm': False, 'File.rm!': False,
               'File.write': False, 'File.write!': False, 'File.rmdir': False},
}
APIS['typescript'] = APIS['javascript']
PARENTS = {'path.dirname', 'filepath.Dir', 'System.IO.Path.GetDirectoryName',
           'dirname', 'File.dirname', 'Path.dirname'}
JOINS = {'path.join', 'path.resolve', 'filepath.Join', 'System.IO.Path.Combine',
         'File.join', 'Path.join'}
CONSTRUCTORS = {'kotlin.io.path.Path', 'java.nio.file.Paths.get', 'java.nio.file.Path.of', 'java.io.File',
                'std::path::Path::new', 'std::path::PathBuf::from'}
# Broad advisory-only recognition, never proof of API identity.
LEADS = re.compile(r'(?:delete|remove|unlink|rmtree|truncate|rm_rf|writeFile|WriteAll|remove_dir)', re.I)
LEX = re.compile(r'''(?P<space>[ \t\r]+)|(?P<newline>\n)|(?P<block>/\*.*?\*/)|(?P<comment>//[^\n]*)|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(?P<word>\$?[A-Za-z_][\w$]*[!?]?)|(?P<op>::|:=|=>|\?\.|[^\s])''', re.S)


@dataclass(frozen=True)
class Token:
    text: str
    kind: str
    start: int
    end: int


def tokens(source, language):
    out = []
    comment_end = -1
    for m in LEX.finditer(source):
        if m.start() < comment_end:
            continue
        if m.group() == '#' and language in ('ruby', 'elixir', 'php', 'shell', 'universal'):
            end = source.find('\n', m.start())
            comment_end = len(source) if end < 0 else end
            continue
        if m.lastgroup not in ('space', 'block', 'comment'):
            out.append(Token(m.group(), m.lastgroup, m.start(), m.end()))
    return out


def literal(token, language):
    text = token.text
    if token.kind != 'string' or text.startswith('`'):
        return None
    if (language in ('php', 'shell') and '$' in text) or (language in ('ruby', 'elixir') and '#{' in text):
        return None
    if text.startswith('"'):
        try:
            return json.loads(text)
        except ValueError:
            return None
    # Single quotes have differing escape semantics: accept only unescaped bodies.
    return text[1:-1] if '\\' not in text else None


def split_args(seq):
    args, current, depth = [], [], 0
    for t in seq:
        if t.text == ',' and depth == 0:
            args.append(current)
            current = []
            continue
        current.append(t)
        if t.text in ('(', '[', '{'):
            depth += 1
        elif t.text in (')', ']', '}'):
            depth -= 1
    if current:
        args.append(current)
    return args


def closing(ts, start):
    depth = 0
    for i in range(start, len(ts)):
        if ts[i].text == '(':
            depth += 1
        elif ts[i].text == ')':
            depth -= 1
            if depth == 0:
                return i
    return None


def name(seq):
    return ''.join(t.text for t in seq if t.kind != 'newline')


def bindings(ts, language):
    """Resolve supported static import forms, never arbitrary unqualified method names."""
    env = {}
    text = [t.text for t in ts]
    if language in ('javascript', 'typescript'):
        for i, t in enumerate(ts):
            module = literal(t, language)
            canonical = {'fs': 'fs', 'node:fs': 'fs', 'fs/promises': 'fs', 'node:fs/promises': 'fs',
                         'path': 'path', 'node:path': 'path'}.get(module)
            if canonical is None:
                continue
            # const f = require('fs'); import f from 'fs'; import * as f from 'fs'
            if i >= 4 and text[i-1] == '(' and text[i-2] == 'require' and text[i-3] == '=':
                env[text[i-4]] = canonical
            elif i >= 3 and text[i-1] == 'from' and ts[i-2].kind == 'word':
                env[text[i-2]] = canonical
    elif language == 'go':
        for i, t in enumerate(ts):
            module = literal(t, language)
            if module in ('os', 'path/filepath'):
                prior = text[i-1] if i else ''
                alias = prior if prior not in ('import', '(') and ts[i-1].kind == 'word' else module.split('/')[-1]
                env[alias] = module.split('/')[-1]
    elif language in ('java', 'csharp', 'kotlin'):
        for i, t in enumerate(ts):
            if t.text not in ('import', 'using'):
                continue
            end = i+1
            while end < len(ts) and ts[end].text not in (';', '\n'):
                end += 1
            full = name(ts[i+1:end])
            if full == 'System.IO':
                for part in ('File', 'Directory', 'Path'):
                    env[part] = full + '.' + part
            elif full.startswith(('java.', 'org.apache.', 'kotlin.')) and '*' not in full:
                env[full.rsplit('.', 1)[-1]] = full
    elif language == 'rust':
        env['std'] = 'std'
        for i, t in enumerate(ts):
            if t.text != 'use':
                continue
            end = i+1
            while end < len(ts) and ts[end].text != ';':
                end += 1
            path = name(ts[i+1:end])
            if path.startswith('std::') and '{' not in path and 'as' not in path:
                env[path.rsplit('::', 1)[-1]] = path
    elif language == 'ruby':
        env.update(File='File', Dir='Dir')
        if any(t.text == 'require' and i+1 < len(ts) and literal(ts[i+1], language) == 'tmpdir' for i,t in enumerate(ts)):
            env['__tmpdir_loaded'] = 'yes'
        if any(t.text == 'require' and i+1 < len(ts) and literal(ts[i+1], language) == 'fileutils' for i,t in enumerate(ts)):
            env['FileUtils'] = 'FileUtils'
    elif language == 'elixir':
        env.update(File='File', Path='Path')
    elif language == 'php':
        env.update({k:k for k in APIS['php']})
        env['dirname'] = 'dirname'
        env['tempnam'] = 'tempnam'
    return env


def canonical(raw, imports):
    head = re.split(r'\.|::', raw)[0]
    return imports.get(head, '') + raw[len(head):] if head in imports else raw if raw.startswith(('System.IO.', 'java.', 'org.apache.')) else ''


def stable_bindings(ts, language, imports):
    """Bindings usable without trusting the flat, execution-order variable map.

    Accept import declarations and qualified uses only. A parameter, bare escape,
    reassignment or member replacement invalidates that identity for this proof.
    This is deliberately whole-candidate conservative, not invented scope analysis.
    """
    declarations = set()
    requires = set()
    scopes, stack = [], []
    macro_context, delimiters = [], []
    origins = {}
    for i, token in enumerate(ts):
        if token.text in (')', ']', '}') and delimiters:
            delimiters.pop()
        macro_context.append(any(delimiters))
        if token.text in ('(', '[', '{'):
            macro = language == 'rust' and (
                (i > 0 and ts[i-1].kind == 'word' and ts[i-1].text.endswith('!'))
                or (i > 1 and ts[i-2].text == 'macro_rules!'))
            delimiters.append(macro)
        if token.text == '}' and stack:
            stack.pop()
        scopes.append(tuple(stack))
        if token.text == '{':
            stack.append(i)

    def declare(found, start, end):
        declarations.update(range(start, end))
        for root in found:
            origins.setdefault(root, []).append(scopes[start])
    for i, token in enumerate(ts):
        if token.text in ('import', 'using', 'use'):
            end = i+1
            while end < len(ts) and ts[end].text not in (';', '\n'):
                end += 1
            found = bindings(ts[i:end], language)
            if found and all(imports.get(k) == v for k,v in found.items()):
                declare(found, i, end)
        if (token.text == 'require' and i >= 3 and i+3 < len(ts) and ts[i-1].text == '='
                and ts[i-3].text in ('const', 'let', 'var')):
            end = closing(ts, i+1) if ts[i+1].text == '(' else None
            if end is not None:
                found = bindings(ts[i-2:end+1], language)
                if found and all(imports.get(k) == v for k,v in found.items()):
                    declare(found, i-2, end+1)
                    requires.update(found)

    def stable(root, callable_name=False):
        for i, token in enumerate(ts):
            if token.kind != 'word' or token.text != root or i in declarations:
                continue
            prev = ts[i-1].text if i else ''
            if prev in ('.', '::'):
                continue  # a property with this spelling is not the binding
            if prev in ('function', 'def', 'defp', 'class', 'module', 'namespace', 'fn', 'mod'):
                return False
            j = i+1
            if callable_name and j < len(ts) and ts[j].text == '(':
                continue
            if j >= len(ts) or ts[j].text not in ('.', '::'):
                return False
            while j+1 < len(ts) and ts[j].text in ('.', '::') and ts[j+1].kind == 'word':
                j += 2
            if j < len(ts) and ts[j].text in ('=', ':=', '[', '+', '-'):
                return False
        return True

    contracts = set(APIS.get(language, {})) | PARENTS | JOINS | CONSTRUCTORS
    candidates = dict(imports)
    # Fully qualified standard-library paths don't require an import declaration.
    if language in ('java', 'kotlin', 'csharp'):
        candidates.update({root:root for root in ('java', 'org', 'System') if root not in candidates})
    dynamic_bindings = any(t.kind == 'word' and t.text in ('eval', 'exec', 'with') for t in ts)
    known = {root:api for root,api in candidates.items()
             if not dynamic_bindings and stable(root, api in contracts)
             and (root not in requires or stable('require', True))}

    def visible(at):
        # A macro's token tree need not execute its apparent calls (stringify!,
        # quote-like macros, etc.). No expansion means no API proof there.
        if macro_context[at]:
            return {}
        scope = scopes[at]
        return {root:api for root,api in known.items() if root not in origins or any(
            scope[:len(origin)] == origin for origin in origins[root])}
    return visible


def expression(seq, variables, imports, language, depth=0):
    if depth > 64:
        return None
    seq = [t for t in seq if t.kind != 'newline']
    if seq and seq[0].text in ('&', 'new'):
        seq = seq[1:]
    if len(seq) == 1:
        if seq[0].kind == 'string':
            text = literal(seq[0], language)
            return PathFact('literal', text) if text is not None else None
        return variables.get(seq[0].text)
    start = next((i for i,t in enumerate(seq) if t.text == '('), None)
    if start is None or closing(seq, start) != len(seq)-1:
        return None
    api = canonical(name(seq[:start]), imports)
    args = [expression(a, variables, imports, language, depth+1) for a in split_args(seq[start+1:-1])]
    if (api == 'System.IO.Path.GetTempFileName' or (api == 'Dir.mktmpdir' and '__tmpdir_loaded' in imports)) and not args:
        return PathFact('temp-file' if api.endswith('GetTempFileName') else 'temp-dir', parent=PathFact('temp-parent'))
    if api == 'fs.mkdtempSync' and len(args) == 1 and args[0] is not None:
        return PathFact('temp-dir', parent=parent_fact(args[0]))
    if api == 'tempnam' and len(args) == 2 and args[0] is not None:
        return PathFact('temp-file', parent=args[0])
    if not args or any(a is None for a in args):
        return None
    if api in PARENTS and len(args) == 1:
        return parent_fact(args[0])
    if api in JOINS or api in CONSTRUCTORS:
        result = args[0]
        for arg in args[1:]:
            result = join_fact(result, arg)
        return result
    return None


def bool_options(ts):
    if len(ts) < 2 or ts[0].text != '{' or ts[-1].text != '}':
        return None
    result = {}
    for part in split_args(ts[1:-1]):
        if len(part) != 3 or part[1].text != ':' or part[2].text not in ('true', 'false'):
            return None
        key = literal(part[0], 'javascript') if part[0].kind == 'string' else part[0].text
        if key not in ('recursive', 'force'):
            return None
        result[key] = part[2].text == 'true'
    return result


def split_lines(ts):
    line = []
    for token in ts:
        if token.kind == 'newline' or token.text == ';':
            yield line
            line = []
        else:
            line.append(token)
    if line:
        yield line


def inspect_source(source, language, workspace, permission):
    ts = tokens(source, language)
    if len(ts) > 20000:
        return Analysis(language, (), 'analysis-limit')
    if language in ('ruby', 'elixir'):
        # Both languages permit a call's parentheses to be omitted. Normalize
        # only known qualified APIs at the start of a statement, preserving spans.
        expanded = []
        for line in split_lines(ts):
            start = next((i for i,t in enumerate(line) if t.kind in ('string',) or (i > 0 and t.kind == 'word' and line[i-1].text not in ('.', '::'))), None)
            if start is not None and name(line[:start]) in APIS[language] and line[start].text != '(':
                expanded.extend(line[:start] + [Token('(', 'op', line[start].start, line[start].start)]
                                + line[start:] + [Token(')', 'op', line[-1].end, line[-1].end)])
            else:
                expanded.extend(line)
            if line:
                expanded.append(Token('\n', 'newline', line[-1].end, line[-1].end))
        ts = expanded
    imports = bindings(ts, language)
    visible_imports = stable_bindings(ts, language, imports)
    variables = {}
    findings = []
    # Scope/control parsing is intentionally not invented for the flat variable
    # map. The closed-root proof below does not depend on that map.
    option_braces = set()
    if language in ('javascript', 'typescript'):
        for i,t in enumerate(ts):
            if t.text == '{':
                end = next((j for j in range(i+1, len(ts)) if ts[j].text in ('{', '}')), None)
                if end is not None and bool_options(ts[i:end+1]) is not None:
                    option_braces.update((i, end))
    uncertain = any(t.text in ('{', '}', '=>', 'if', 'unless', 'for', 'while', 'try', 'catch', 'def',
                               'defp', 'fn', 'function', 'class', 'module', 'namespace', 'eval', 'exec',
                               'return', 'throw', 'raise', 'exit', 'die', 'goto', 'break', 'continue',
                               'rescue', 'ensure', 'begin', 'do', 'end', 'case', 'cond', 'with')
                    and i not in option_braces for i,t in enumerate(ts))
    apis = APIS.get(language, {})
    if any(t.text in ('=', ':=') and i and (ts[i-1].text in (']', '}') or (i > 1 and ts[i-2].text == ',')) for i,t in enumerate(ts)):
        uncertain = True
    for i, t in enumerate(ts):
        if t.text == '=' and i > 1 and ts[i-1].text in ('+', '-', '*', '/', '?', '|', '&'):
            variables[ts[i-2].text] = None
            imports.pop(ts[i-2].text, None)
        if t.text in ('=', ':=') and i and ts[i-1].kind == 'word':
            end = i+1
            while end < len(ts) and ts[end].text not in (';', '\n'):
                end += 1
            variable = ts[i-1].text
            if i > 2 and ts[i-2].text in ('.', '::'):
                root = i-3
                while root > 1 and ts[root-1].text in ('.', '::'):
                    root -= 2
                imports.pop(ts[root].text, None)
            variables[variable] = expression(ts[i+1:end], variables, imports, language)
            # Import declaration assignment is the one legitimate alias initializer.
            if variable in imports and not any(x.text == 'require' for x in ts[i+1:end]):
                imports.pop(variable)
        if t.text != '(' or i == 0:
            continue
        begin = i-1
        while begin >= 2 and ts[begin-1].text in ('.', '::', '?.') and ts[begin-2].kind == 'word':
            begin -= 2
        raw = name(ts[begin:i])
        api_name = raw
        api = canonical(api_name, imports)
        end = closing(ts, i)
        if end is None:
            continue
        args = split_args(ts[i+1:end])
        recognized = api in apis
        target = expression(args[0], variables, imports, language) if args else None
        recursive = apis.get(api, False)
        if language == 'kotlin' and raw.endswith('.deleteRecursively') and imports.get('deleteRecursively') == 'kotlin.io.path.deleteRecursively':
            # Imported extension on a receiver, not a fictitious first-argument API.
            target = expression(ts[begin:i-2], variables, imports, language)
            api_name = 'deleteRecursively'
            api = imports[api_name]
            recognized, recursive = True, True
        if not recognized and not LEADS.search(raw):
            continue
        # rm/rmdir and Directory.Delete are recursive only with their explicit option.
        if api in ('fs.rm', 'fs.rmSync', 'fs.rmdir', 'fs.rmdirSync'):
            options = bool_options(args[1]) if len(args) > 1 else None
            recursive = bool(options and options.get('recursive'))
        if api == 'System.IO.Directory.Delete':
            recursive = len(args) > 1 and name(args[1]) == 'true'
        possible = uncertain
        if is_root(target):
            closed_imports = visible_imports(begin)
            root = re.split(r'\.|::', api_name)[0]
            identity_known = root in closed_imports and canonical(api_name, closed_imports) == api
            if not identity_known:
                recognized = False
            elif args:
                # Evaluate again WITHOUT variables from other branches/scopes.
                # Also require stable identities for every qualified path helper.
                roots = {tok.text for j,tok in enumerate(args[0]) if tok.kind == 'word'
                         and (j == 0 or args[0][j-1].text not in ('.', '::'))
                         and j+1 < len(args[0]) and args[0][j+1].text in ('.', '::')}
                closed_target = expression(args[0], {}, closed_imports, language)
                if roots <= closed_imports.keys() and is_root(closed_target):
                    possible = False
        confidence, rule = classify((target,) if target is not None else (), workspace, permission, recursive, possible)
        if not recognized:
            confidence, rule = 'UNKNOWN', 'unresolved'
        findings.append(Finding(confidence, rule,
                                source.count('\n', 0, ts[begin].start)+1,
                                source[ts[begin].start:ts[end].end], (target.text or target.kind,) if target is not None else ()))
    return Analysis(language, tuple(findings), 'supported-subset' if language in APIS else 'universal-lexical-only')
