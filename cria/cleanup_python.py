"""Small abstract interpreter for Python paths; never imports or executes candidate code.

Assumes imports of os/shutil/tempfile/pathlib resolve to standard-library semantics.
Recognizes aliases and invalidates shadowed bindings. Unknown calls, dynamic code,
monkey-patching, symlinks and cwd changes are not certified. Relative paths remain
unknown. Function summaries are limited to undecorated zero-argument helpers.
"""
import ast
import posixpath
from .cleanupfacts import Analysis, Finding, PathFact as Atom, classify, parent_fact, join_fact


UNKNOWN = frozenset({Atom('unknown')})


def value(kind, text='', parent=None):
    return frozenset({Atom(kind, text, parent)})


def union(*values):
    return frozenset().union(*values) or UNKNOWN


def unpath(atoms):
    return frozenset(a.parent if a.kind == 'path' else a for a in atoms)


def merge(*states):
    return {key: union(*(s.get(key, UNKNOWN) for s in states)) for key in set().union(*states)}


class PythonPaths:
    def __init__(self, source, workspace, permission):
        self.source, self.workspace, self.permission = source, workspace, permission
        self.findings = []
        self.functions = {}
        self.active = set()
        self.steps = 0

    def target(self, node, targets, recursive=False, possible=False):
        targets = unpath(targets)
        confidence, rule = classify(targets, self.workspace, self.permission, recursive, possible)
        finding = Finding(confidence, rule,
                          node.lineno, ast.get_source_segment(self.source, node) or '',
                          tuple(sorted({a.text or a.kind for a in targets})))
        if finding not in self.findings:
            self.findings.append(finding)

    def parent(self, atoms):
        return frozenset(parent_fact(a) for a in atoms)

    def join(self, left, right):
        return frozenset(join_fact(a, b) for a in left for b in right) or UNKNOWN

    def expr(self, n, env, report=True, possible=False):
        self.steps += 1
        if self.steps > 50000:
            raise ValueError('analysis budget')
        if n is None:
            return UNKNOWN
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return value('literal', n.value)
        if isinstance(n, ast.Name):
            return env.get(n.id, value('api', 'builtins.open') if n.id == 'open' else UNKNOWN)
        if isinstance(n, ast.Attribute):
            base = self.expr(n.value, env, report, possible)
            if n.attr == 'name' and all(a.kind in ('temp-context', 'temp-stream') for a in base):
                return frozenset(a.parent for a in base)
            if n.attr == 'parent':
                return frozenset(Atom('path', parent=p) for p in self.parent(base)) if all(a.kind == 'path' for a in base) else UNKNOWN
            return union(*(value('api', a.text + '.' + n.attr) if a.kind == 'api' else UNKNOWN for a in base))
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            left = self.expr(n.left, env, report, possible)
            right = self.expr(n.right, env, report, possible)
            return frozenset(Atom('path', parent=a) for a in self.join(unpath(left), unpath(right))) if all(a.kind == 'path' for a in left) else UNKNOWN
        if isinstance(n, ast.NamedExpr):
            atoms = self.expr(n.value, env, report, possible)
            self.bind(n.target, atoms, env)
            return atoms
        if isinstance(n, ast.IfExp):
            return union(self.expr(n.body, env, report, True), self.expr(n.orelse, env, report, True))
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            atoms = self.expr(n.value, env, report, possible)
            if n.slice.value == 1:
                return union(*(frozenset({a.parent}) if a.kind == 'mkstemp' else UNKNOWN for a in atoms))
        if not isinstance(n, ast.Call):
            for child in ast.iter_child_nodes(n):
                if isinstance(child, ast.expr):
                    self.expr(child, env, report, possible)
            return UNKNOWN
        if isinstance(n.func, ast.Name) and n.func.id in ('exec', 'eval'):
            for key in [*env, 'open']:
                env[key] = UNKNOWN
            return UNKNOWN
        funcs = self.expr(n.func, env, report, possible)
        args = [self.expr(a, env, report, possible) for a in n.args]
        kw = {k.arg: self.expr(k.value, env, report, possible) for k in n.keywords}
        first = args[0] if args else kw.get('path', kw.get('file', kw.get('filename', UNKNOWN)))
        # Do not give a union of known and shadowed callees a definite identity.
        api = next(iter(funcs)).text if len(funcs) == 1 and next(iter(funcs)).kind == 'api' else ''
        if api == 'os.path.dirname':
            return self.parent(first)
        if api in ('os.path.join', 'pathlib.Path', 'pathlib.PurePosixPath'):
            result = unpath(first)
            for arg in args[1:]:
                result = self.join(result, unpath(arg))
            return frozenset(Atom('path', parent=a) for a in result) if api.startswith('pathlib.') else result
        if api == 'os.path.normpath':
            return union(*(value('literal', posixpath.normpath(a.text)) if a.kind == 'literal' else UNKNOWN for a in first))
        if api == 'tempfile.NamedTemporaryFile':
            # Its positional parameter layout differs from mkstemp/mkdtemp.
            if args:
                return UNKNOWN
            parents = kw.get('dir', value('temp-parent'))
            return frozenset(Atom('temp-stream', parent=Atom('temp-file', parent=a)) for a in parents)
        if api in ('tempfile.mkstemp', 'tempfile.mkdtemp', 'tempfile.TemporaryDirectory'):
            # Positional dir is supported only when its documented position is present.
            directory = kw.get('dir', args[2] if len(args) > 2 else None)
            parents = directory if directory is not None else value('temp-parent')
            kind = 'temp-file' if api == 'tempfile.mkstemp' else 'temp-dir'
            resources = frozenset(Atom(kind, parent=a) for a in parents)
            if api == 'tempfile.TemporaryDirectory':
                return frozenset(Atom('temp-context', parent=a) for a in resources)
            return frozenset(Atom('mkstemp', parent=a) for a in resources) if kind == 'temp-file' else resources
        if api in ('shutil.rmtree', 'os.remove', 'os.unlink', 'os.rmdir', 'os.removedirs'):
            if report:
                self.target(n, first, api == 'shutil.rmtree', possible)
            return UNKNOWN
        if api in ('builtins.open', 'io.open'):
            mode = args[1] if len(args) > 1 else kw.get('mode', value('literal', 'r'))
            if report and any(a.kind == 'literal' and any(c in a.text for c in 'wax+') for a in mode):
                self.target(n, first, possible=possible or len(mode) != 1)
            return UNKNOWN
        if isinstance(n.func, ast.Attribute) and n.func.attr in ('unlink', 'rmdir', 'write_text', 'write_bytes', 'open'):
            # Only path-constructor/derived receivers, not arbitrary objects with the same method name.
            receiver = n.func.value
            if self.is_path(receiver, env):
                target = self.expr(receiver, env, False, possible)
                mode = args[0] if args else kw.get('mode', value('literal', 'r'))
                writing = n.func.attr != 'open' or any(a.kind == 'literal' and any(c in a.text for c in 'wax+') for a in mode)
                if report and writing:
                    self.target(n, target, possible=possible)
        if api.startswith('helper:') and not args and not kw and api not in self.active:
            fn = self.functions[api]
            # No path-insensitive summary of conditional returns/fallthrough.
            if not fn.body or not isinstance(fn.body[-1], ast.Return) or any(
                    not isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Import, ast.ImportFrom, ast.Return))
                    for stmt in fn.body):
                return UNKNOWN
            self.active.add(api)
            local = self.function_env(fn, env)
            _, returns = self.block(fn.body, local, False, possible)
            self.active.remove(api)
            return union(*returns)
        return UNKNOWN

    def is_path(self, node, env):
        return all(a.kind == 'path' for a in self.expr(node, env, False))

    def bind(self, target, atoms, env):
        if isinstance(target, ast.Name):
            env[target.id] = atoms
        elif isinstance(target, (ast.Tuple, ast.List)):
            for i, item in enumerate(target.elts):
                self.bind(item, union(*(frozenset({a.parent}) if a.kind == 'mkstemp' and i == 1 else UNKNOWN for a in atoms)), env)
        elif isinstance(target, ast.Attribute):
            # A mutation of a module invalidates its imported identity in this scope.
            root = target
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                identities = [a.text for a in env.get(root.id, UNKNOWN) if a.kind == 'api']
                for key, atoms in list(env.items()):
                    if any(a.kind == 'api' and any(a.text == ident or a.text.startswith(ident + '.')
                                                  for ident in identities) for a in atoms):
                        env[key] = UNKNOWN
                env[root.id] = UNKNOWN

    def function_env(self, fn, env):
        local = dict(env)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                local[n.id] = UNKNOWN
            if isinstance(n, ast.arg):
                local[n.arg] = UNKNOWN
        return local

    def block(self, nodes, env, report=True, possible=False):
        returns = []
        for n in nodes:
            if isinstance(n, ast.Import):
                for a in n.names:
                    env[a.asname or a.name.split('.')[0]] = value('api', a.name if a.asname else a.name.split('.')[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == '*':
                        for key in [*env, 'open']:
                            env[key] = UNKNOWN
                    else:
                        env[a.asname or a.name] = (value('api', (n.module or '') + '.' + a.name)
                                                  if not n.level else UNKNOWN)
            elif isinstance(n, ast.ClassDef):
                # The class suite executes now, but its bindings do not become
                # globals visible to method bodies. Register methods for the
                # separate function pass, whose parameters remain unknown.
                self.block(n.body, dict(env), report, possible)
                env[n.name] = UNKNOWN
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = 'helper:' + str(n.lineno)
                self.functions[key] = n
                env[n.name] = (value('api', key) if not n.decorator_list and not n.args.args
                               and not n.args.posonlyargs and not n.args.kwonlyargs and not n.args.vararg and not n.args.kwarg else UNKNOWN)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                atoms = self.expr(n.value, env, report, possible)
                for target in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    self.bind(target, atoms, env)
            elif isinstance(n, ast.Expr):
                self.expr(n.value, env, report, possible)
            elif isinstance(n, ast.Return):
                returns.append(self.expr(n.value, env, report, possible))
                break
            elif isinstance(n, (ast.Raise, ast.Break, ast.Continue)):
                break
            elif isinstance(n, ast.If):
                self.expr(n.test, env, report, possible)
                if isinstance(n.test, ast.Constant) and isinstance(n.test.value, (bool, int)):
                    env, ret = self.block(n.body if n.test.value else n.orelse, env, report, possible)
                    returns.extend(ret)
                else:
                    a, ra = self.block(n.body, dict(env), report, possible)
                    b, rb = self.block(n.orelse, dict(env), report, possible)
                    env = merge(a, b)
                    returns.extend(ra + rb)
            elif isinstance(n, (ast.For, ast.While)):
                self.expr(n.iter if isinstance(n, ast.For) else n.test, env, report, possible)
                if ((isinstance(n, ast.For) and isinstance(n.iter, (ast.List, ast.Tuple)) and not n.iter.elts)
                        or (isinstance(n, ast.While) and isinstance(n.test, ast.Constant) and n.test.value is False)):
                    env, more = self.block(n.orelse, env, report, possible)
                    returns.extend(more)
                    continue
                before = dict(env)
                if isinstance(n, ast.For):
                    items = n.iter.elts if isinstance(n.iter, (ast.List, ast.Tuple)) else []
                    self.bind(n.target, union(*(self.expr(x, env, report, possible) for x in items)), env)
                after, ret = self.block(n.body, dict(env), report, True)
                env = merge(before, after)
                env, more = self.block(n.orelse, env, report, True)
                returns.extend(ret + more)
            elif isinstance(n, ast.Try):
                # finally may run after ANY prefix throws; retain each prefix's bindings.
                states = [dict(env)]
                abrupt = any(isinstance(x, (ast.Return, ast.Raise, ast.Break, ast.Continue)) for x in ast.walk(n))
                for stmt in n.body:
                    env, ret = self.block([stmt], env, report, possible or abrupt)
                    states.append(dict(env))
                    returns.extend(ret)
                normal, ret = self.block(n.orelse, dict(env), report, possible)
                states.append(normal)
                returns.extend(ret)
                for handler in n.handlers:
                    branch, ret = self.block(handler.body, merge(*states), report, True)
                    states.append(branch)
                    returns.extend(ret)
                env, ret = self.block(n.finalbody, merge(*states), report, possible or abrupt)
                returns.extend(ret)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for item in n.items:
                    atoms = self.expr(item.context_expr, env, report, possible)
                    if item.optional_vars:
                        entered = frozenset(a.parent if a.kind == 'temp-context' else a for a in atoms)
                        self.bind(item.optional_vars, entered, env)
                env, ret = self.block(n.body, env, report, possible)
                returns.extend(ret)
            else:
                # Unsupported statements never retain potentially overwritten path facts.
                for child in ast.walk(n):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                        env[child.id] = UNKNOWN
        return env, returns


def inspect_source(source, workspace, permission):
    tree = ast.parse(source)
    engine = PythonPaths(source, workspace, permission)
    env, _ = engine.block(tree.body, {})
    # Analyze function bodies with parameters unknown, under final module bindings.
    for fn in list(engine.functions.values()):
        if not fn.decorator_list:
            engine.block(fn.body, engine.function_env(fn, env))
    return Analysis('python', tuple(engine.findings), 'supported-subset')
