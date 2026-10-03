"""Narrow, inert-source mutation contracts for additional languages.

Only closed path expressions are resolved: no flat cross-scope variable map,
execution, compiler, imports or filesystem observations. Library identity and
lexical uncertainty are independent of whether a call is conditional. Unsupported
syntax/dispatch stays UNKNOWN. These adapters are not cria-wide language support.
"""
from dataclasses import dataclass
import re

from .cleanupfacts import Analysis, Finding, PathFact, classify, join_fact, parent_fact
from .cleanup_languages import Token, LEADS, name

LANGUAGES = {
    '.c': 'c', '.h': 'c', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp',
    '.hpp': 'cpp', '.hh': 'cpp', '.hxx': 'cpp', '.swift': 'swift',
    '.m': 'objective-c', '.mm': 'objective-c', '.dart': 'dart', '.lua': 'lua',
    '.pl': 'perl', '.pm': 'perl', '.r': 'r', '.jl': 'julia',
    '.ps1': 'powershell', '.psm1': 'powershell',
}
_CLIKE = {'c', 'cpp', 'swift', 'objective-c', 'dart'}
_WORD = re.compile(r'\$?[A-Za-z_][\w]*[!?]?')
_LONG_LUA = re.compile(r'\[(=*)\[')


def _block_end(source, start, opening, closing, nested=False, escaped=False):
    i, depth = start + len(opening), 1
    while i < len(source):
        if escaped and source[i] == '\\':
            i += 2
        elif nested and source.startswith(opening, i):
            depth += 1
            i += len(opening)
        elif source.startswith(closing, i):
            depth -= 1
            i += len(closing)
            if not depth:
                return i
        else:
            i += 1
    raise SyntaxError('unterminated comment or quote')


def lex(source, language):
    """Keep source spans; consume comments/quoted regions before scanning calls."""
    out, i, uncertain = [], 0, False
    while i < len(source):
        start, c = i, source[i]
        if c in ' \t\r':
            i += 1
            continue
        if c == '\n':
            out.append(Token(c, 'newline', i, i+1))
            i += 1
            continue
        at_line_start = not source[source.rfind('\n', 0, i)+1:i].strip()
        if language in ('c', 'cpp', 'objective-c') and c == '#' and at_line_start:
            end = source.find('\n', i)
            end = len(source) if end < 0 else end
            # Only direct include/import declarations establish library identity.
            # Other directives (macros, conditional preprocessing) need expansion.
            directive = source[i:end]
            out.append(Token(directive, 'directive', i, end))
            if not re.fullmatch(r'#\s*(?:include|import)\s*<[^>]+>\s*', directive):
                uncertain = True
            i = end
            continue
        if language in _CLIKE and source.startswith('/*', i):
            i = _block_end(source, i, '/*', '*/', language in ('swift', 'dart'))
            continue
        if language == 'julia' and source.startswith('#=', i):
            i = _block_end(source, i, '#=', '=#', True)
            continue
        if language == 'powershell' and source.startswith('<#', i):
            i = _block_end(source, i, '<#', '#>', True)
            continue
        if language == 'lua':
            comment = source.startswith('--', i)
            long = _LONG_LUA.match(source, i+2 if comment else i)
            if long:
                delimiter = ']' + long[1] + ']'
                end = source.find(delimiter, long.end())
                if end < 0:
                    raise SyntaxError('unterminated Lua long bracket')
                i = end + len(delimiter)
                if not comment:
                    out.append(Token(source[long.end():end].removeprefix('\n'), 'literal', start, i))
                continue
        line_comment = ((language in _CLIKE and source.startswith('//', i))
                        or (language == 'lua' and source.startswith('--', i))
                        or (language in ('perl', 'r', 'julia', 'powershell') and c == '#'))
        if line_comment:
            end = source.find('\n', i)
            i = len(source) if end < 0 else end
            continue
        if language == 'perl' and at_line_start and re.match(r'__(?:DATA|END)__\b', source[i:]):
            out.append(Token(source[i:], 'opaque', i, len(source)))
            break
        if language == 'perl' and c == '=' and at_line_start and re.match(r'=\w', source[i:]):
            end = re.search(r'^=cut\b[^\n]*', source[i:], re.M)
            if not end:
                raise SyntaxError('unterminated Perl POD')
            i += end.end()
            continue
        if language == 'powershell' and source[i:i+2] in ("@'", '@"'):
            quote = source[i+1]
            end = re.search(r'^' + re.escape(quote + '@'), source[i+2:], re.M)
            if not end:
                raise SyntaxError('unterminated PowerShell here-string')
            i += 2 + end.end()
            out.append(Token(source[start:i], 'opaque', start, i))
            continue
        if language in ('cpp', 'objective-c') and re.match(r'(?:u8|u|U|L)?R"', source[i:]):
            raw = re.match(r'(?:u8|u|U|L)?R"([^\s()\\]{0,16})\(', source[i:])
            if not raw:
                raise SyntaxError('unsupported raw string')
            delimiter = ')' + raw[1] + '"'
            end = source.find(delimiter, i+raw.end())
            if end < 0:
                raise SyntaxError('unterminated raw string')
            body = source[i+raw.end():end]
            i = end + len(delimiter)
            out.append(Token(body, 'literal', start, i))
            continue
        if language == 'perl':
            quoted = re.match(r'(q[qwxr]?|m|s|tr|y)\s*([^\w\s])', source[i:])
            if quoted:
                opening = quoted[2]
                closing = {'(': ')', '{': '}', '[': ']', '<': '>'}.get(opening, opening)
                begin = i + quoted.end()-1
                i = _block_end(source, begin, opening, closing, opening != closing, escaped=True)
                kind = 'words' if quoted[1] == 'qw' else 'opaque'
                out.append(Token(source[begin+1:i-1], kind, start, i))
                # Substitution has a second body; don't interpret it as executable.
                if quoted[1] in ('s', 'tr', 'y'):
                    uncertain = True
                continue
        # Raw Swift strings and R raw strings are deliberately opaque to proof.
        if ((language == 'swift' and c == '#') or
                (language == 'r' and source[i:i+2] in ('r"', 'R"'))):
            uncertain = True
        prefix = (language == 'objective-c' and source.startswith('@"', i)) or (
            language == 'dart' and c in 'rR' and source[i+1:i+2] in ('"', "'"))
        if prefix:
            i += 1
            c = source[i]
        if c in ('"', "'", '`'):
            quote = c
            triple = language in ('swift', 'dart', 'julia') and source.startswith(c*3, i)
            delimiter = c*3 if triple else c
            body_start = i + len(delimiter)
            i = body_start
            while i < len(source):
                if source.startswith(delimiter, i):
                    if language == 'powershell' and not triple and source.startswith(c*2, i):
                        i += 2
                        continue
                    break
                escape = ('`' if quote == '"' else None) if language == 'powershell' else '\\'
                if language == 'dart' and prefix:
                    escape = None
                if escape is not None and source[i] == escape:
                    i += 2
                else:
                    i += 1
            if i >= len(source):
                raise SyntaxError('unterminated string')
            body = source[body_start:i]
            i += len(delimiter)
            interpolated = ((language in ('perl', 'julia', 'powershell') and quote != "'" and '$' in body)
                            or (language == 'perl' and quote == '"' and '@' in body)
                            or (language == 'dart' and not prefix and '$' in body))
            escaped = (('`' in body or quote*2 in body) if language == 'powershell' else '\\' in body)
            kind = 'opaque' if interpolated or escaped or quote == '`' or triple else 'literal'
            if language in ('c', 'cpp', 'objective-c', 'julia') and quote == "'":
                kind = 'opaque'  # character/adjoint, not a filesystem path
            out.append(Token(body, kind, start, i))
            continue
        match = _WORD.match(source, i)
        if match:
            i = match.end()
            out.append(Token(match[0], 'word', start, i))
        else:
            op = next((op for op in ('::', '<<-', '<-', '<<', '=>', '==', '!=', '+=', '-=') if source.startswith(op, i)), c)
            i += len(op)
            out.append(Token(op, 'op', start, i))
            if language == 'perl' and op in ('/', '<<'):
                uncertain = True  # regex/heredoc delimiters are not ordinary calls
        if len(out) > 20000:
            raise ValueError('token budget')
    return out, uncertain


def end_group(ts, start):
    pairs = {'(': ')', '[': ']', '{': '}'}
    stack = []
    for i in range(start, len(ts)):
        text = ts[i].text
        if ts[i].kind in ('literal', 'opaque', 'words', 'directive'):
            continue
        if text in pairs:
            stack.append(pairs[text])
        elif text in (')', ']', '}'):
            if not stack or stack.pop() != text:
                return None
            if not stack:
                return i
    return None


def call_start(ts, end):
    """Qualified identifier before '('; receiver expressions handled separately."""
    begin = end-1
    if begin < 0 or ts[begin].kind != 'word':
        return end
    while begin >= 2 and ts[begin-1].text in ('.', '::') and ts[begin-2].kind == 'word':
        begin -= 2
    return begin


def arguments(seq):
    """Separate arguments, never punctuation that is itself a string literal."""
    result, current, depth = [], [], 0
    for token in seq:
        if token.kind == 'op':
            if token.text in (',', ';') and depth == 0:
                result.append(current)
                current = []
                continue
            if token.text in ('(', '[', '{'):
                depth += 1
            elif token.text in (')', ']', '}'):
                depth -= 1
        current.append(token)
    if current:
        result.append(current)
    return result


def positional(args):
    return [a for a in args if not (len(a) >= 2 and a[0].kind == 'word' and a[1].text in (':', '='))]


def keyword(args, label):
    values = [a[2:] for a in args if len(a) >= 2 and a[0].text == label and a[1].text in (':', '=')]
    return values[0] if len(values) == 1 else []


def argument(args, position, label=None):
    named = keyword(args, label) if label else []
    plain = positional(args)
    return named or (plain[position] if position < len(plain) else [])


def stable(ts, raw, module=False, bare=False):
    """Whole-candidate conservative identity: reject overrides, escapes, parameters.

    This does not establish lexical scope or detect reflective monkey-patching.
    It only authorizes the documented direct library/builtin spellings.
    """
    parts = re.split(r'(\.|::)', raw)
    for i, token in enumerate(ts):
        if token.kind != 'word' or [t.text for t in ts[i:i+len(parts)]] != parts:
            continue
        if i and ts[i-1].text in ('.', '::'):
            continue
        prev = ts[i-1].text if i else ''
        j = i + len(parts)
        if prev in ('function', 'sub', 'class', 'struct', 'namespace', 'module', 'local', 'let', 'var', 'const', 'typedef', 'typealias', 'def'):
            return False
        if module:
            if j >= len(ts) or ts[j].text not in ('.', '::', '('):
                return False
            while j+1 < len(ts) and ts[j].text in ('.', '::') and ts[j+1].kind == 'word':
                j += 2
            if j < len(ts) and ts[j-1].text == 'ofstream' and ts[j].kind == 'word':
                j += 1  # std::ofstream stream(path): a constructor declaration
        if j < len(ts) and ts[j].text == '(':
            end = end_group(ts, j)
            if end is not None and end+1 < len(ts) and ts[end+1].text in ('=', '<-', '{'):
                return False
            if not module and prev and ts[i-1].kind == 'word' and prev not in ('return', 'try', 'await', 'new'):
                return False  # declarations, not ordinary calls
        elif not (bare and j < len(ts) and (ts[j].kind in ('literal', 'opaque') or ts[j].text.startswith('$'))):
            return False
    return True


@dataclass(frozen=True)
class Contract:
    recursive: bool = False
    target: int = 0
    label: str | None = None
    mode: int | None = None


class Inspector:
    def __init__(self, source, language, workspace, permission):
        self.source, self.language = source, language
        self.workspace, self.permission = workspace, permission
        self.ts, self.uncertain = lex(source, language)
        self.findings = []
        self.contracts = {}
        self.helpers = {}
        self._stable = {}
        self._contracts()

    def _contracts(self):
        ts, lang, contracts = self.ts, self.language, self.contracts
        headers = set()
        declarations = set()
        for i, t in enumerate(ts):
            if t.kind == 'directive':
                match = re.fullmatch(r'#\s*(?:include|import)\s*<([^>]+)>\s*', t.text)
                if match:
                    headers.add(match[1])
                    declarations.add(i)
            if t.kind == 'word' and t.text in ('import', 'use', 'require'):
                end = i+1
                while end < len(ts) and ts[end].text not in (';', '\n'):
                    end += 1
                declarations.update(range(i, end))
        # Imports are identity evidence, not value uses or runtime calls.
        self.identity_ts = [t for i,t in enumerate(ts) if i not in declarations]
        if lang in ('c', 'cpp', 'objective-c'):
            if headers & {'stdio.h', 'cstdio'}:
                contracts.update(remove=Contract(), fopen=Contract(mode=1))
            if 'unistd.h' in headers:
                contracts.update(unlink=Contract(), rmdir=Contract())
            if lang == 'cpp':
                if 'cstdio' in headers:
                    contracts.update({'std::remove': Contract(), 'std::fopen': Contract(mode=1)})
                if 'fstream' in headers:
                    contracts['std::ofstream'] = Contract()
                if 'filesystem' in headers:
                    contracts.update({'std::filesystem::remove_all': Contract(True), 'std::filesystem::remove': Contract()})
                    self.helpers['std::filesystem::path'] = 'constructor'
        if lang == 'swift':
            imported = any(t.kind == 'word' and t.text == 'import' and i+1 < len(ts) and ts[i+1].text == 'Foundation' for i,t in enumerate(ts))
            if imported:
                contracts.update({'FileManager.default.removeItem': Contract(True, label='atPath'),
                                  'FileManager.default.createFile': Contract(label='atPath')})
                self.helpers['URL'] = 'url'
        if lang == 'objective-c':
            self.foundation = 'Foundation/Foundation.h' in headers
        if lang == 'dart':
            self.dart_io = any(t.kind == 'word' and t.text == 'import' and i+2 < len(ts) and ts[i+1].kind == 'literal'
                               and ts[i+1].text == 'dart:io' and ts[i+2].text == ';' for i,t in enumerate(ts))
        if lang == 'lua':
            contracts.update({'os.remove': Contract(), 'io.open': Contract(mode=1)})
        if lang == 'perl':
            contracts.update({'unlink': Contract(), 'rmdir': Contract(), 'open': Contract(target=2, mode=1),
                              'CORE::unlink': Contract(), 'CORE::rmdir': Contract(), 'CORE::open': Contract(target=2, mode=1)})
            for i,t in enumerate(ts):
                if t.kind == 'word' and t.text in ('use', 'require') and name(ts[i+1:i+4]) == 'File::Path':
                    contracts['File::Path::remove_tree'] = Contract(True)
                    if i+4 < len(ts) and ts[i+4].kind == 'words' and 'remove_tree' in ts[i+4].text.split():
                        contracts['remove_tree'] = Contract(True)
        if lang == 'r':
            for prefix in ('', 'base::'):
                contracts.update({prefix+'unlink': Contract(label='x'), prefix+'file.remove': Contract(),
                                  prefix+'writeLines': Contract(target=1, label='con')})
                self.helpers[prefix+'dirname'] = 'parent'
                self.helpers[prefix+'file.path'] = 'join'
        if lang == 'julia':
            for prefix in ('', 'Base.'):
                contracts.update({prefix+'rm': Contract(), prefix+'open': Contract(mode=1), prefix+'write': Contract()})
                self.helpers[prefix+'dirname'] = 'parent'
                self.helpers[prefix+'joinpath'] = 'join'
        dynamic = {'lua': {'load', 'loadstring', 'setfenv', 'rawset'}, 'perl': {'eval'},
                   'r': {'eval', 'assign'}, 'julia': {'eval'}, 'powershell': {'Invoke-Expression', 'Set-Alias', 'New-Alias'}}
        if any(t.kind == 'word' and t.text in dynamic.get(lang, set()) for t in ts):
            self.uncertain = True
        # PowerShell command names and switches are case insensitive.
        if lang == 'powershell':
            self.ts = [Token(t.text.lower() if t.kind == 'word' else t.text, t.kind, t.start, t.end) for t in ts]
            if any(name(self.ts[i:i+3]) in ('set-alias', 'new-alias', 'invoke-expression') for i in range(len(ts))):
                self.uncertain = True
        if lang == 'julia' and any(t.kind == 'word' and t.text == 'quote' for t in ts):
            self.uncertain = True  # block quotes require Julia's full nesting grammar

    def known(self, raw):
        if raw not in self.contracts and raw not in self.helpers:
            return False
        root = re.split(r'\.|::', raw)[0]
        module = root in ('std', 'FileManager', 'os', 'io', 'File', 'CORE', 'Base', 'base') and raw != root
        key = root if module else raw
        if (key, module) not in self._stable:
            self._stable[key, module] = stable(self.identity_ts, key, module, self.language == 'perl')
        return self._stable[key, module]

    def path(self, seq, depth=0):
        seq = [t for t in seq if t.kind != 'newline']
        if depth > 64:
            raise ValueError('expression budget')
        if len(seq) == 1 and seq[0].kind == 'literal':
            return PathFact('literal', seq[0].text)
        if seq and seq[0].text == '(' and end_group(seq, 0) == len(seq)-1:
            return self.path(seq[1:-1], depth+1)
        start = next((i for i,t in enumerate(seq) if t.text == '(' and t.kind == 'op'), None)
        if start is None or end_group(seq, start) != len(seq)-1:
            return None
        raw = name(seq[:start])
        if raw not in self.helpers or not self.known(raw):
            return None
        args = arguments(seq[start+1:-1])
        if self.helpers[raw] == 'url':
            return self.path(keyword(args, 'fileURLWithPath'), depth+1)
        facts = [self.path(a, depth+1) for a in args]
        if not facts or any(f is None for f in facts):
            return None
        if self.helpers[raw] == 'parent':
            return parent_fact(facts[0]) if len(facts) == 1 else None
        if self.helpers[raw] == 'constructor':
            return facts[0] if len(facts) == 1 else None
        result = facts[0]
        for fact in facts[1:]:
            result = join_fact(result, fact)
        return result

    def emit(self, start, end, target, recursive=False, known=True):
        confidence, rule = classify((target,) if target else (), self.workspace, self.permission, recursive)
        if not known or self.uncertain:
            confidence, rule = 'UNKNOWN', 'unresolved'
        self.findings.append(Finding(confidence, rule, self.source.count('\n', 0, start)+1,
                                     self.source[start:end], (target.text or target.kind,) if target else ()))

    def call(self, raw, args, start, end):
        contract = self.contracts.get(raw)
        if contract is None:
            if LEADS.search(raw):
                self.emit(start, end, self.path(argument(args, 0)), known=False)
            return
        known = self.known(raw)
        if contract.mode is not None:
            mode_seq = argument(args, contract.mode)
            mode = self.path(mode_seq)
            if mode is None and not mode_seq and self.language in ('lua', 'julia'):
                flags = [keyword(args, flag) for flag in ('write', 'append', 'truncate', 'create')]
                if self.language == 'lua' or not any(flags):
                    return  # default read mode
                if any(name(flag) == 'true' for flag in flags):
                    mode = PathFact('literal', 'w')
                elif all(not flag or name(flag) == 'false' for flag in flags):
                    return
            if mode is not None:
                if self.language == 'perl':
                    mutating = mode.text in ('>', '>>', '+<', '+>', '+>>')
                    if mode.text == '<':
                        return
                else:
                    mutating = bool(re.fullmatch(r'[rwa][b+tx]*', mode.text)) and (mode.text[0] in 'wa' or '+' in mode.text)
                    if re.fullmatch(r'r[btx]*', mode.text):
                        return
                known &= mutating
            else:
                known = False
        recursive = contract.recursive
        if self.language in ('r', 'julia') and raw.rsplit('::', 1)[-1].rsplit('.', 1)[-1] in ('unlink', 'rm'):
            flag = keyword(args, 'recursive')
            if not flag and self.language == 'r':
                flag = argument(args, 1)
            recursive = name(flag) == ('TRUE' if self.language == 'r' else 'true')
        target_seq = argument(args, contract.target, contract.label)
        if self.language == 'swift' and raw.endswith('.removeItem') and not target_seq:
            target_seq = keyword(args, 'at')
        variadic = ((self.language == 'perl' and raw.rsplit('::', 1)[-1] in ('unlink', 'remove_tree'))
                    or (self.language == 'r' and raw.rsplit('::', 1)[-1] == 'file.remove'))
        for target in positional(args) if variadic else [target_seq]:
            self.emit(start, end, self.path(target), recursive, known)

    def dart(self, i):
        """Direct constructor receivers only, never an arbitrary .delete method."""
        ts = self.ts
        if ts[i].text not in ('Directory', 'File') or i+1 >= len(ts) or ts[i+1].text != '(':
            return
        if i and ts[i-1].text in ('.', '::'):
            return
        close = end_group(ts, i+1)
        if close is None or close+3 >= len(ts) or ts[close+1].text != '.' or ts[close+3].text != '(':
            return
        method = ts[close+2].text
        if method not in ('delete', 'deleteSync', 'writeAsString', 'writeAsStringSync', 'writeAsBytes', 'writeAsBytesSync'):
            return
        finish = end_group(ts, close+3)
        if finish is None:
            return
        args = arguments(ts[close+4:finish])
        known = self.dart_io and stable(self.identity_ts, ts[i].text)
        if method.startswith('write') and ts[i].text != 'File':
            known = False
        recursive = name(keyword(args, 'recursive')) == 'true' if method.startswith('delete') else False
        target = self.path(argument(arguments(ts[i+2:close]), 0))
        self.emit(ts[i].start, ts[finish].end, target, recursive, known)

    def objc(self, i):
        ts = self.ts
        end = end_group(ts, i)
        if end is None or i+1 >= end or ts[i+1].text != '[':
            return
        receiver_end = end_group(ts, i+1)
        if receiver_end is None or receiver_end+2 >= end:
            return
        receiver = name(ts[i+2:receiver_end])
        selector = ts[receiver_end+1].text
        if selector not in ('removeItemAtPath', 'createFileAtPath') or ts[receiver_end+2].text != ':':
            return
        value_start = receiver_end+3
        value_end = value_start
        while value_end < end:
            if value_end+1 < end and ts[value_end].kind == 'word' and ts[value_end+1].text == ':':
                break
            value_end += 1
        # NSFileManager is a class receiver, not a free callable. Reject a local
        # declaration/override explicitly; don't grant identity to arbitrary id.
        known = self.foundation and receiver == 'NSFileManagerdefaultManager'
        if any(t.text == 'NSFileManager' and j and ts[j-1].text not in ('[',) for j,t in enumerate(self.identity_ts)):
            known = False
        self.emit(ts[i].start, ts[end].end, self.path(ts[value_start:value_end]), selector == 'removeItemAtPath', known)

    def powershell(self):
        ts = self.ts
        for i,t in enumerate(ts):
            if t.kind != 'word' or t.text not in ('remove', 'clear', 'set') or i+2 >= len(ts):
                continue
            command = name(ts[i:i+3])
            if command not in ('remove-item', 'clear-content', 'set-content'):
                continue
            if i and (ts[i-1].kind not in ('op', 'newline') or ts[i-1].text not in ('\n', ';', '{', '}', '|', '&')):
                continue
            end = i+3
            while end < len(ts) and ts[end].text not in ('\n', ';', '}', '|'):
                end += 1
            args, switches, positional_args = ts[i+3:end], {}, []
            j = 0
            while j < len(args):
                if args[j].text == '-' and j+1 < len(args) and args[j+1].kind == 'word':
                    key = args[j+1].text
                    j += 2
                    begin = j
                    while j < len(args) and args[j].text != '-':
                        j += 1
                    switches[key] = args[begin:j]
                else:
                    positional_args.append(args[j])
                    j += 1
            whatif = switches.get('whatif')
            if whatif is not None and (not whatif or name(whatif) == ':$true'):
                continue
            recursive = 'recurse' in switches and name(switches['recurse']) in ('', ':$true')
            target_seq = switches.get('literalpath', switches.get('path', positional_args))
            known = not any(name(ts[k:k+3]) == command and k and ts[k-1].text == 'function' for k in range(len(ts)))
            if whatif is not None and name(whatif) != ':$false':
                known = False
            for target in arguments(target_seq) or [[]]:
                self.emit(t.start, ts[end-1].end, self.path(target), recursive, known)

    def inspect(self):
        if self.language == 'powershell':
            self.powershell()
        else:
            ts = self.ts
            held_until = -1
            for i,t in enumerate(ts):
                if i <= held_until:
                    continue
                if self.language == 'julia' and t.kind == 'op' and t.text == '@':
                    j = i+1
                    while j < len(ts) and (ts[j].kind == 'word' or ts[j].text == '.'):
                        j += 1
                    if j < len(ts) and ts[j].text == '(':
                        held_until = end_group(ts, j) or j
                    else:
                        while j < len(ts) and ts[j].text not in ('\n', ';'):
                            j += 1
                        held_until = j-1
                    continue
                if self.language == 'perl' and t.kind == 'word':
                    j = i+1
                    while j+1 < len(ts) and ts[j].text == '::' and ts[j+1].kind == 'word':
                        j += 2
                    raw = name(ts[i:j])
                    if raw in self.contracts and j < len(ts) and ts[j].text != '(' and (i == 0 or ts[i-1].text != '::'):
                        end = j
                        while end < len(ts) and ts[end].text not in (';', '\n', '}', 'if', 'unless'):
                            end += 1
                        self.call(raw, arguments(ts[j:end]), t.start, ts[end-1].end)
                if self.language == 'objective-c' and t.text == '[' and t.kind == 'op':
                    self.objc(i)
                if self.language == 'dart' and t.kind == 'word':
                    self.dart(i)
                if t.text != '(' or t.kind != 'op':
                    continue
                if self.language == 'julia' and i and ts[i-1].text == ':':
                    end = end_group(ts, i)
                    if end is not None:
                        held_until = end
                    continue
                begin = call_start(ts, i)
                if begin == i:
                    continue
                # foo.remove and Directory(...).delete are not free remove/delete.
                if begin and ts[begin-1].text in ('.', '::'):
                    continue
                end = end_group(ts, i)
                if end is None:
                    continue
                raw = name(ts[begin:i])
                held = ((self.language in ('c', 'cpp') and raw in ('sizeof', 'decltype', 'noexcept', 'alignof', '_Generic'))
                        or (self.language == 'r' and raw in ('quote', 'expression', 'substitute', 'base::quote', 'base::expression', 'base::substitute')))
                if held:
                    held_until = end
                    continue
                if (self.language == 'cpp' and begin >= 3 and name(ts[begin-3:begin]) == 'std::ofstream'
                        and (begin == 3 or ts[begin-4].text not in ('.', '::'))):
                    self.call('std::ofstream', arguments(ts[i+1:end]), ts[begin-3].start, ts[end].end)
                else:
                    self.call(raw, arguments(ts[i+1:end]), ts[begin].start, ts[end].end)
        return Analysis(self.language, tuple(self.findings), 'supported-subset')


def inspect_source(source, language, workspace, permission):
    try:
        return Inspector(source, language, workspace, permission).inspect()
    except SyntaxError:
        return Analysis(language, (), 'invalid-source')
    except (ValueError, RecursionError):
        return Analysis(language, (), 'analysis-limit')
