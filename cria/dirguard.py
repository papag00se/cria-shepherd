"""External-directory permission — a cria-side bound on what the driven model's file tools may touch
OUTSIDE the workspace, enforced independently of the harness's own sandbox. So a harness run with its
approvals/sandbox turned OFF (``--yolo``/``danger-full-access``) is still restricted when it fronts a
fledgling, untrusted model.

Levels (config ``[safety] external_dir_permission``, default ``none``):
  * ``none``  — no reads or writes outside the workspace.
  * ``read``  — external reads allowed; external writes refused.
  * ``write`` — no external-directory restriction (the harness's own sandbox, if any, still applies).

Enforced at the tool-call chokepoint (``writeproxy.translate_outbound``): a violating synthetic file
tool or raw shell command is replaced with a refusal the model reads and self-corrects from. It is
ROBUST for the explicit paths of the synthetic file tools (write_file/edit_file/read_file/list_dir),
and BEST-EFFORT for raw shell — a heuristic path/verb scan that a determined model could obfuscate,
so it is a backstop for a WEAK model, not a security sandbox. The harness sandbox stays the real
boundary; this restricts a model the operator hasn't yet learned to trust.
"""

from __future__ import annotations

import os
import re
import shutil

from . import prompts, toolpath

LEVELS = ("none", "read", "write")

# Absolute or ~-anchored FILE path tokens in a shell command. The lookbehind rejects a `/` that
# follows a word char, dot, COLON, or SLASH — so RELATIVE paths (`a/b`, `./x`, `.venv/bin`) AND URLs
# (`https://host/path`, `//host`) are NOT matched; only a rooted single-`/...` or `~/...`. This guard
# governs the FILESYSTEM, never the network — a `curl https://…`/`wget` must never be mistaken for an
# external file access. The token ends at whitespace or a shell metacharacter.
_PATH_TOKEN = re.compile(r"(?<![\w.:/])(?:~/|/(?!/))[^\s'\";|&><()`$*]*")
# Does the command WRITE (create/modify/delete a file) rather than only read? Heuristic: a write verb,
# or a `>`/`>>` redirection to a file (but not `>&`, an fd dup like `2>&1`).
_WRITE_VERB = re.compile(
    r"(?:^|[\s;&|(])(?:rm|mv|cp|dd|tee|mkdir|rmdir|touch|truncate|ln|chmod|chown|install|rsync)\b"
    r"|\bsed\s+-i\b|>>?(?![&\s]*&)", re.IGNORECASE)
# A MUTATING command verb (write via the verb's operands) — _WRITE_VERB WITHOUT the `>>?` redirect. A
# redirect writes to ITS target, checked per-token by _is_write_target; only the verb form needs a
# whole-command scan (a `rm /external` mutates the external path). Splitting them stops a plain
# `grep /etc/hosts > local.txt` — whose only write verb is the redirect to a LOCAL file — from being
# false-refused as an external "write" (the redirect target is local; the external path is only read).
_MUTATING_VERB = re.compile(
    r"(?:^|[\s;&|(])(?:rm|mv|cp|dd|tee|mkdir|rmdir|touch|truncate|ln|chmod|chown|install|rsync)\b"
    r"|\bsed\s+-i\b", re.IGNORECASE)

# A command that makes a NETWORK request — a network URL scheme (even one built across a variable, the
# literal scheme still appears in the command text) or a known HTTP client. In such a command the
# rooted path-shaped tokens are almost always URL PATH fragments (`f'{BASE}/handles/goose'` → the regex
# sees `/handles/goose` after the `}`), NOT filesystem paths. This guard governs the FILESYSTEM, so it
# must never refuse a network call — the recurring footgun where a `requests.get(...)` read as an
# "external file" derailed the model into a false "no network from shell" theory.
_NETWORK_CMD = re.compile(
    r"\b(?:https?|ftps?|wss?)://|\b(?:curl|wget|requests|urllib3?|httpx|aiohttp|http\.client|socket)\b",
    re.IGNORECASE)
# The one external FILE access that survives the network-command exemption: an explicit write TARGET —
# the path is preceded by a `>`/`>>` redirect or a `-o`/`-O`/`--output`/`tee` (so `curl … -o /etc/x` and
# `curl … > /tmp/y` are still caught, but a URL path in the request is not).
_WRITE_TARGET_BEFORE = re.compile(r"(?:>>?|(?:^|\s)-[oO]|(?:^|\s)--output|(?:^|\s)tee)\s*$")

# A text-SEARCH / stream-edit tool whose QUOTED argument is a PATTERN or script, never a file path — so a
# rooted-looking quoted term (`grep "/handles/{handle}"`, `sed "s#/api/v1#X#"`) is the search expression,
# not an external file access. Files these tools touch are given as bare (unquoted) path args, which the
# scan still catches. Keyed off the command verb (generic shell knowledge, not model/harness-specific).
_TEXT_SEARCH_LEAD = re.compile(r"(?:^|[\s;&|(])(?:e?grep|fgrep|rg|ag|ack|sed|awk|gawk)\b", re.IGNORECASE)


# --- Installs: an external write whose destination the command never NAMES -------------------
#
# Every rule above reasons about a path token IN the command. A package manager takes its
# destination from the environment, so `pip install -e .` writes into the user's real
# site-packages while naming nothing outside the workspace — and the path scan finds nothing to
# refuse. Measured 2026-08-01: a run's `pip install -e .` left an `__editable__…pth` in the user's
# site-packages pointing at that run's /tmp workspace; two days later it was still on sys.path for
# every Python process on the box, shadowing `import handle_resolver` for later runs AND for the
# suite's own verifier.
#
# Matched here are only invocations whose destination is SHARED by default. A manager that
# installs into the project by default is absent on purpose: `npm install` (./node_modules),
# `composer require` (./vendor), `bundle install`, `cargo add`, `go get` are ordinary
# workspace-local work and must pass untouched. Their global FORMS are matched.
_GLOBAL_INSTALL = re.compile(
    r"(?:^|[\s;&|(])(?:"
    r"(?:pip|pip3|python3?\s+-m\s+pip)\s+install"          # user/system site-packages
    r"|(?:npm|pnpm|yarn)\s+(?:install|add|i)\b(?=[^;&|]*(?:\s-g\b|\s--global\b))"
    r"|(?:gem|cargo|go)\s+install"                          # ~/.gem, ~/.cargo/bin, GOPATH/bin
    r"|composer\s+global\b"
    r"|(?:apt|apt-get|dnf|yum|pacman|apk|brew)\s+(?:install|add)\b"
    r")", re.IGNORECASE)

# The same command made workspace-local. Any ONE of these means the install lands inside the
# project, so it is ordinary work: an interpreter/pip run from a RELATIVE path (`./.venv/bin/pip`),
# an explicit destination flag, or a venv activated in the same command line.
_LOCAL_INSTALL_SCOPE = re.compile(
    r"(?:^|[\s;&|(])\.{0,2}/?[\w.-]*(?:venv|env|virtualenv)[\w.-]*/bin/"   # ./.venv/bin/pip …
    r"|--target(?:=|\s)|--prefix(?:=|\s)|--root(?:=|\s)"
    # The same idea in the other ecosystems: a destination inside the project. gem's --install-dir
    # and bundler's --path are Ruby's form, composer's --working-dir is PHP's. Without these the
    # guard refuses the very route its own remediation now recommends.
    r"|--install-dir(?:=|\s)|--path(?:=|\s)|--working-dir(?:=|\s)"
    r"|(?:^|[\s;&|(])(?:source|\.)\s+\.{0,2}/?[\w.-]*(?:venv|env)[\w.-]*/bin/activate",
    re.IGNORECASE)


# A KILL THAT SELECTS BY PATTERN, NAME OR PORT reaches every matching process on the machine, not
# just the ones this run started. Same hole `install_refusal` was written for and says so in its own
# docstring: "the destination is decided by the environment, so there is no token to find". A path
# scan sees nothing in `pkill -f uvicorn`, and there is nothing for it to see.
#
# MEASURED, orders-api-py x nemotron-elastic, cycle 1: the coder ran `pkill -f uvicorn` and
# `kill $(lsof -t -i :8081)` and took down the OPERATOR'S systemd services six times, plus an
# unrelated service on port 9091 three more. It was trying to free a port for its own server, which
# is legitimate work — the selector was not.
#
# `kill <pid>` is untouched. A literal pid is a process the coder has identified, which is the whole
# difference between stopping your own server and clearing the machine.
_PATTERN_KILL = re.compile(
    r"(?:^|[\s;&|(])(?:"
    r"pkill\b|killall\b|fuser\b[^;&|]*\s-k\b|skill\b"
    r"|kill\b[^;&|]*\$\("                       # kill $(lsof …) / kill $(pgrep …)
    r"|kill\b[^;&|]*`"                            # backtick form
    r")", re.IGNORECASE)


def kill_refusal(command: str, level: str) -> str | None:
    """The refusal for a kill whose SELECTOR is unbounded, or None. Allowed at ``write``, the level
    that means the operator accepted an unrestricted process.

    Deliberately NOT a security control — the same best-effort posture as the rest of raw-shell
    handling, and the same reason: a weak model reaching past the workspace usually does it by
    accident, and the cheapest fix is to say so at the moment it happens."""
    if level == "write" or not command:
        return None
    if not _PATTERN_KILL.search(command):
        return None
    return prompts.load("pattern_kill_refusal")


def install_refusal(command: str, level: str, workspace: str | None) -> str | None:
    """The refusal for an install whose destination is SHARED, or None when allowed.

    Deliberately NOT a security control — the same best-effort posture as the rest of raw-shell
    handling. It closes the one hole that is invisible to a path scan by construction: the
    destination is decided by the environment, so there is no token to find.

    Allowed at ``write``, since that level means "no external-directory restriction" and an
    operator who set it has accepted exactly this. Refused at ``read`` too: ``read`` permits
    external READS, and an install is a write.
    """
    if level == "write" or not command:
        return None
    if not _GLOBAL_INSTALL.search(command):
        return None
    if _LOCAL_INSTALL_SCOPE.search(command):
        return None
    return prompts.fill(prompts.load("external_install_refusal"),
                        root=f" ({workspace})" if workspace else "",
                        local=_local_install_advice(command))


# A guard that REFUSES in six ecosystems must REMEDIATE in six. The trigger above already matches
# pip, npm/pnpm/yarn -g, gem, cargo, go, composer global and the system managers — and the whole
# remedy was pip and a venv, so a refused `gem install countries` was answered with Python. Measured
# on the six-language battery's ruby task: with no ruby-viable route offered, the coder hand-rolled
# the data the gem would have provided.
#
# AND A ROUTE MUST BE ONE THIS MACHINE CAN ACTUALLY TAKE. The ruby row prescribed
# `bundle install --path vendor/bundle`; `bundle` is not installed on the box the battery runs on.
# Two runs followed it into `bundle: command not found` and spent the rest of the run on transport.
# cria refused a real command and answered with an imaginary one — a false claim about the world,
# one step removed (#5b), and exactly the knowledge cria can settle for free with `which`.
#
# So each ecosystem lists its routes in preference order, and each route names the tools it needs.
# The first route whose tools are ALL present wins. Where none are available the honest answer is
# the empty one — say what is forbidden and stop, which is already how apt, dnf, brew and pacman are
# handled: they install to the machine and have no project-local form, so no route is invented (#3).
_INSTALL_REMEDY = (
    (re.compile(r"(?:pip|pip3|python3?\s+-m\s+pip)\s+install", re.I),
     (("pip_venv", ("python3",)),)),
    (re.compile(r"(?:npm|pnpm|yarn)\s+(?:install|add|i)\b", re.I),
     (("npm_local", ("npm",)),)),
    # Two ruby routes, bundler first because a Gemfile is the durable record. `gem_direct` is the
    # fallback the box actually supports, and it says how to make the gem LOADABLE — installing to
    # vendor/bundle without putting it on the load path is the failure that cost a 100% ruby run.
    (re.compile(r"\bgem\s+install", re.I),
     # `ruby` joins bundler's needs because the route now names a one-off `<ruby> -e` command, and a
     # route may only print a binary cria has actually resolved (#5b — the whole reason `{{TOOL}}`
     # tokens exist). A ruby project without ruby on PATH has bigger problems than this sentence.
     (("gem_bundler", ("bundle", "ruby")), ("gem_direct", ("gem",)))),
    (re.compile(r"\bcargo\s+install", re.I),
     (("cargo_add", ("cargo",)),)),
    (re.compile(r"\bgo\s+install", re.I),
     (("go_get", ("go",)),)),
    (re.compile(r"composer\s+global", re.I),
     (("composer_local", ("composer",)),)),
    (re.compile(r"\bmvn\s+install\b", re.I),
     (("maven_dep", ("mvn",)),)),
)


def installs_outside_workspace(command: str) -> bool:
    """This command installs a package somewhere that is NOT the project directory.

    The same two patterns `install_refusal` weighs, minus the permission level — because the question
    here is not "may this run" but "does this change the workspace", and the answer to that does not
    depend on what the operator allowed. A global install writes into a shared environment; a local
    one (`--path vendor/bundle`, a venv, `npm install` with no `-g`) really does populate the project
    and is not this.

    Read by the repetition tracker: `mkdir -p vendor/bundle && gem install eu_countries` carries a
    mutator word, so the word scan called it progress on new ground and FLUSHED the loop it was in
    the middle of."""
    return bool(command and _GLOBAL_INSTALL.search(command)
                and not _LOCAL_INSTALL_SCOPE.search(command))


def _tool_present(name: str) -> bool:
    """Is this tool on PATH right now? The one question that separates a real route from a guess.

    On the CODER's path, not cria's: this advice is a sentence telling the coder which command to
    run, so the only PATH that can make it true is the one the coder's commands use. cria's service
    PATH has none of the user's toolchains, which turned every route through them into "no route"
    (#5b — see :mod:`cria.toolpath`)."""
    if toolpath.which(name) is not None:
        return True
    # A DISTRO MAY SHIP IT UNDER A VERSIONED NAME. Debian installs bundler as `bundle3.2`; there is no
    # plain `bundle` on this box. Asked name-exactly, cria concluded "ruby has no project-local route"
    # and fell through to the weaker advice — while the tool it wanted was on PATH the whole time,
    # and `bundle3.2 install --path vendor/bundle` scores 5/5 on the task that advice is for.
    #
    # This is not guessing a name: the directory is READ and a real file is found, or the answer stays
    # False (#5b). The same shape as the two commits that already fixed this function twice — a
    # sentence asserting something about this machine that cria never asked the machine.
    return _resolved_tool(name) is not None


def _resolved_tool(name: str) -> str | None:
    """The name the coder must actually TYPE for this tool, or None when it is not on their PATH.

    The plain name when it exists, otherwise the versioned executable that does. `_tool_present` is
    this question reduced to a bool, and keeping the answer is what stops cria selecting a route on
    the strength of `bundle3.2` and then telling the coder to run `bundle` (#5b)."""
    if toolpath.which(name) is not None:
        return name
    return _versioned_variant(name)


def _versioned_variant(name: str) -> str | None:
    """The `<name><version>` executable actually present on the coder's PATH, or None.

    Distros version the binary rather than the package: `bundle3.2`, `python3.12`, `pip3`, `gem3.2`.
    Every directory on the path is listed and matched against `name` plus digits and dots — nothing
    is constructed and probed, so a name that does not exist cannot be reported as present."""
    import re as _re
    pat = _re.compile(rf"^{_re.escape(name)}[0-9][0-9.]*$")
    for d in (toolpath.coder_path() or "").split(os.pathsep):
        try:
            for entry in os.listdir(d):
                if pat.match(entry) and os.access(os.path.join(d, entry), os.X_OK):
                    return entry
        except OSError:
            continue
    return None


def _local_install_advice(command: str) -> str:
    """The project-local route for the manager that was actually refused, or "" when there is none.

    An empty string is a real answer, and now for two reasons. apt, dnf, brew and pacman install to
    the machine and have no project-local form. And an ecosystem whose tools are not installed has
    no route cria can honestly offer either — better to state only what is forbidden than to send
    the coder after a command that cannot run (#3, #5b).

    THE ROUTE NAMES THE BINARY THAT WAS ACTUALLY FOUND. `_tool_present` answers a bool, so the route
    used to be selected on the strength of `bundle3.2` and then printed with the literal `bundle` —
    which does not exist on this box. Measured on shipping-rates-rb × ternary-bonsai, cycle 2: ten
    refusals, all naming `bundle install --path vendor/bundle`, calls 0037–0057 spent on installs
    that could not succeed, 80% → 20%. The coder never tried `bundle3.2` because nothing named it.
    That is the same #5b failure the header of `install_remedy.txt` already records as fixed twice:
    the DISCOVERY was repaired and the SENTENCE was left behind. Now the discovered name is filled
    into the route's `{{TOOL}}` token, so the two can no longer disagree."""
    routes = prompts.load_map("install_remedy")
    for pat, options in _INSTALL_REMEDY:
        if not pat.search(command):
            continue
        for key, needs in options:
            found = {t: _resolved_tool(t) for t in needs}
            if all(found.values()) and routes.get(key):
                # THE TWO ANSWER DIFFERENT QUESTIONS, so they must not be glued together. The route
                # says how to add a DEPENDENCY to the project; `_already_here` fires only when the
                # thing being installed is the route's own TOOL, and once cria has said the tool is
                # already here there is no install left to route. Concatenating them produced, in one
                # message on shipping-rates-rb x ternary-bonsai 1787102312: "You do not need to
                # install it. Install it into the project instead: add the gem to a `Gemfile`…" —
                # a contradiction, whose second half is about a different package (#5b, #3).
                here = _already_here(command, found, routes)
                if here:
                    return here
                return " " + prompts.fill(routes[key],
                                          **{t.upper(): n for t, n in found.items()})
        return ""      # the ecosystem is refused, and nothing here can carry out the alternative
    return ""


def _already_here(command: str, found: dict, routes: dict) -> str:
    """"You do not need to install that — it is already here, under this name." — or "".

    The circular answer, walked on cycle 4 cell 13 (`shipping-rates-rb x ternary-bonsai`, 10% useful,
    and 34 of its 54 calls spent trying to obtain a gem). The coder ran

        which bundler 2>&1; gem install bundler 2>&1 | tail -5

    and cria refused it with the `gem_bundler` route — *"add the gem to a `Gemfile` and run
    `bundle3.2 install --path vendor/bundle`"* — which answers "install bundler" with "run bundler".
    cria had ALREADY resolved the binary: that is where the string `bundle3.2` in its own sentence
    came from. And because the refusal takes the whole command line, the `which bundler` that would
    have told the coder the truth never executed. Two calls later: *"The bundler install is
    restricted. Let me try to manually extract the gem file I downloaded earlier"*. It never learned
    bundler was installed.

    Only fires when the thing being installed IS a tool the chosen route names, so it cannot speak
    about an ordinary package (#3). The fact goes FIRST, because the route below it is the part the
    coder already read past six times."""
    line = routes.get("already_present", "")
    if not line:
        return ""
    for tool, resolved in found.items():
        # The refused command names this very tool as its package — `gem install bundler` for the
        # route that runs `bundle3.2`. Matched on the tool's stem so `bundler`/`bundle` are one word.
        stem = tool.rstrip("0123456789.")
        m = re.search(rf"install\s+(?:--?\S+\s+)*({re.escape(stem)}\w*)\b", command, re.I)
        if m:
            # The coder's OWN word for it — it typed `bundler`, and a message that answers with
            # `bundle` reads as being about something else.
            return " " + prompts.fill(line, PACKAGE=m.group(1), TOOL=str(resolved))
    return ""


def _is_write_target(command: str, start: int) -> bool:
    """True when the path token at ``start`` is the target of a file WRITE (a redirect or an output
    flag) — the only external file access still refused inside a network command."""
    return bool(_WRITE_TARGET_BEFORE.search(command[:start]))


def _quoted_spans(command: str) -> list[tuple[int, int]]:
    """(start, end) CONTENT ranges of single/double-quoted strings in the command. Used to skip a rooted
    path token that sits INSIDE a quote as a non-initial word — a search PATTERN, not a file: `grep -n
    "GET /handles" file` names no `/handles` FILE; the `/handles` is the grep term. Without this the guard
    refused the coder's own grep (the exact action cria's spill outline tells it to run), citing a path it
    never touched. A quote that OPENS with the path (`cat "/etc/my file"`) is still a real path — only a
    token that starts AFTER the quote's content-start is treated as a pattern. Best-effort: an unbalanced
    quote runs its span to end-of-string (degrades safe — over-skips, never over-refuses)."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in "\"'":
            j = command.find(c, i + 1)
            if j == -1:
                spans.append((i + 1, n)); break
            spans.append((i + 1, j)); i = j + 1
        else:
            i += 1
    return spans


def _is_param_value_quote(command: str, content_start: int) -> bool:
    """Does the quote whose CONTENT starts at ``content_start`` open a ``key=`` assignment?

    `shell="/bin/bash"` is a PARAMETER VALUE, not a path the command opens — the difference from
    `cat "/etc/x"` is the `=` in front of the quote, and it is the whole difference. Measured: 9
    distinct commands, 229 occurrences, where a weak model wrote a tool SIGNATURE as a shell command
    (`exec_command cmd="go mod tidy", justification="…", shell="/bin/bash"`) and cria refused it for
    the interpreter named in the last parameter. That refusal names nothing the coder can change —
    the command was never a shell command — which is exactly what #5b forbids: validate that a
    command is well-formed before judging it, and never turn a partial match into a world fact."""
    q = content_start - 1                      # the quote character itself
    i = q - 1
    while i >= 0 and command[i] == " ":        # `key = "…"` is the same assignment
        i -= 1
    return i >= 0 and command[i] == "="


def _after_unresolved_expansion(command: str, start: int) -> bool:
    """Is this rooted token the TAIL of a shell expansion cria cannot resolve?

    `ls $(go env GOPATH)/pkg/github.com/…` contains no path the coder wrote: the leading component
    comes from a command cria never ran, so whether the result is inside the workspace is unknown —
    and #11b is explicit that a mechanism which cannot observe the thing it is judging must abstain
    rather than answer. It answered: 11 distinct commands, 263 occurrences, all refused for a suffix.
    Together with the parameter-value case that is 492 of 1,242 captured refusals, 40%."""
    i = start - 1
    if i < 0 or command[i] not in ")}":
        return False
    close, opener = command[i], "(" if command[i] == ")" else "{"
    depth = 0
    while i >= 0:
        if command[i] == close:
            depth += 1
        elif command[i] == opener:
            depth -= 1
            if depth == 0:
                return i > 0 and command[i - 1] == "$"
        i -= 1
    return False


def normalize_level(value: str | None) -> str:
    v = (value or "none").strip().lower()
    return v if v in LEVELS else "none"


def is_external(path: str, workspace: str | None) -> bool:
    """True when ``path`` resolves OUTSIDE ``workspace``. Lexical (normpath, no disk touch) so it
    works on a not-yet-existing path and ``..`` cannot escape the check. A relative path resolves
    against the workspace → internal; an absolute/``~`` path is internal only if it IS, or is under,
    the workspace. With no known workspace, any rooted path is treated as external."""
    if not path or not path.strip():
        return False
    p = os.path.expanduser(path.strip())
    if not workspace:
        return os.path.isabs(p) or path.strip().startswith("~")
    ws = os.path.normpath(os.path.expanduser(workspace))
    full = os.path.normpath(p if os.path.isabs(p) else os.path.join(ws, p))
    return full != ws and not full.startswith(ws + os.sep)


def escapes_workspace(path: str, workspace: str | None) -> bool:
    """True when ``path`` resolves outside ``workspace`` AFTER following symlinks — the containment
    question for a path cria is about to ACT on (execute, delete), where the thing exists.

    THE COMPANION TO :func:`is_external`, AND THE DIFFERENCE IS THE POINT. `is_external` is lexical
    on purpose: it must answer for a write target that does not exist yet, and `normpath` alone stops
    `..` escaping. But a symlink inside the workspace pointing out is INTERNAL to a lexical check and
    OUTSIDE to a real one, so the two answers genuinely differ — and both are correct for their own
    caller.

    Nothing said so. `probegate.sweep_litter` hand-rolled the realpath version because deleting
    through a symlink is how you delete someone else's files, while `writeproxy` used the lexical one
    because a refusal must work on a path the model has only proposed. Two right answers, two
    implementations, no name for either distinction — so a third caller (`execcheck`, which runs the
    coder's program, and `planner_tools`, which runs a research shell) picked NEITHER and simply did
    not check. "Is this safe here" had three implementations that could not agree.

    Fails CLOSED: an unresolvable path, an unreadable parent or no known workspace all answer True.
    A path cria cannot place is a path cria must not act on."""
    if not path or not path.strip() or not workspace:
        return True
    try:
        base = os.path.realpath(os.path.expanduser(str(workspace)))
        p = os.path.expanduser(str(path).strip())
        full = p if os.path.isabs(p) else os.path.join(base, p)
        # realpath the PARENT: the leaf itself may be a symlink we are about to remove rather than
        # follow, and resolving it would ask about its target instead of about the link.
        parent = os.path.realpath(os.path.dirname(full) or base)
        whole = os.path.realpath(full)
    except (OSError, ValueError):
        return True
    # The directory ITSELF is inside itself. Resolving only the parent answers "is my container
    # inside the base", which is False for the base — caught when planner_tools' `_within` started
    # delegating here and `_within(root, root)` flipped from True to False with the whole suite still
    # green. The parent is what must not be followed for a LEAF (a symlink we may be deleting);
    # the whole path settles the base case.
    if whole == base:
        return False
    return parent != base and not parent.startswith(base + os.sep)


# System I/O plumbing — NOT external data. `2>/dev/null`, `> /dev/stderr`, `/dev/fd/…` etc. are
# ordinary shell redirection targets and device files; never treat them as an external file access.
# /proc and /sys are read-only kernel views a coder legitimately inspects. This guard is about the
# model reaching into another PROJECT's files, not the OS's plumbing.
_EXEMPT_PREFIXES = ("/dev/", "/proc/", "/sys/")
_EXEMPT_EXACT = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty"}


def _exempt(path: str) -> bool:
    """A system path the guard must always allow (device/plumbing), even under ``none``."""
    p = os.path.normpath(os.path.expanduser(path.strip()))
    return p in _EXEMPT_EXACT or any(p == pre.rstrip("/") or p.startswith(pre) for pre in _EXEMPT_PREFIXES)


def _typo_fold(s: str) -> str:
    """Case-fold and collapse dash/underscore — the two one-glyph workspace-typo classes walked so
    far. Anything looser would start matching genuinely different directories."""
    return os.path.normpath(os.path.expanduser(s.strip())).lower().replace("_", "-")


def _case_typo_of_workspace(path: str, workspace: str | None) -> bool:
    """True when ``path`` IS the workspace (or a path under it) up to LETTER CASE or a
    DASH/UNDERSCORE swap — i.e. the model typed its own project directory one glyph wrong.

    Walked on ada-handles_gemma4_codex_poff_1785869053: the coder wrote ``…-8Ibs7re8`` (capital I)
    for its real ``…-8ibs7re8`` workspace 106 times, drew this refusal 50+ times — the message
    printed both strings side by side, and a temp-0 12B never spotted the one-letter difference;
    it invented "absolute paths are forbidden" and spiralled ~300 calls. Hours after the case fix,
    ada-handles_mellum2_codex_poff_1785880114 hit the SAME loop one glyph over: ``suite-ada_handles``
    (underscore) for ``suite-ada-handles`` — the note never fired because the fix was
    letter-case-only. The comparison is exact ground truth cria already holds; naming the
    difference is the one sentence that ends the loop at its first firing."""
    if not workspace:
        return False
    p, ws = _typo_fold(path), _typo_fold(workspace)
    return p == ws or p.startswith(ws + os.sep)


def _refusal(verb: str, path: str, workspace: str | None = None) -> str:
    # prompts/external_path_refusal.txt — {{PATH}} takes the quoted repr, matching the old f"{path!r}".
    # {{ROOT}} names the ACTUAL project directory when known: the anonymous "the project directory"
    # left a blocked model inventing roots (/tmp/src, /tmp/project) for whole runs — the refusal is
    # the one place cria can state the real one.
    root = f" ({workspace})" if workspace else ""
    note = prompts.load("external_path_case_note") if _case_typo_of_workspace(path, workspace) else ""
    return prompts.fill(prompts.load("external_path_refusal"), verb=verb, path=repr(path), root=root,
                        casenote=note)


def path_refusal(path: str, is_write: bool, level: str, workspace: str | None) -> str | None:
    """The refusal for a synthetic file tool's EXPLICIT path, or None when allowed. read_file/list_dir
    are reads; write_file/edit_file are writes."""
    if level == "write" or _exempt(path) or not is_external(path, workspace):
        return None
    if level == "read" and not is_write:
        return None
    return _refusal("Writing" if is_write else "Reading", path, workspace)


def command_refusal(command: str, level: str, workspace: str | None) -> str | None:
    """The refusal for a RAW shell command, or None when allowed — heuristic: refuse when the command
    names an external absolute/``~`` path, weighed against whether it looks like a write. Under
    ``none`` any external path is refused; under ``read`` only an external WRITE is."""
    if level == "write" or not command:
        return None
    # An install writes outside the workspace WITHOUT naming a path, so it must be judged before
    # the path scan — which by construction finds nothing to refuse in it.
    installing = install_refusal(command, level, workspace)
    if installing:
        return installing
    # Same class, judged in the same place: a selector that reaches outside the workspace without
    # naming a path, so the scan below can never see it.
    killing = kill_refusal(command, level)
    if killing:
        return killing
    network = bool(_NETWORK_CMD.search(command))
    search_cmd = bool(_TEXT_SEARCH_LEAD.search(command))
    spans = _quoted_spans(command)
    external = None
    ext_is_write = False
    for m in _PATH_TOKEN.finditer(command):
        tok = m.group(0)
        # A rooted token INSIDE a quoted string is a search PATTERN / literal, not a filesystem path,
        # when EITHER it does not open the quote (a mid-quote term like "GET /handles") OR the command is a
        # text-search/stream-edit tool whose quoted args are patterns ("/handles/{handle}" to grep is the
        # search term, not a file). A quoted path that opens the quote for a FILE command (`cat "/etc/x"`)
        # is still checked. Files for grep/sed are bare path args, which the scan still catches.
        inside = next((s for s, e in spans if s <= m.start() < e), None)
        if inside is not None and (m.start() != inside or search_cmd
                                   or _is_param_value_quote(command, inside)):
            continue
        if _after_unresolved_expansion(command, m.start()):
            continue
        if not is_external(tok, workspace) or _exempt(tok):
            continue
        # In a network request, a rooted path token is a URL fragment, not a file access — exempt it
        # unless it is an explicit write TARGET (curl -o /etc/x, > /tmp/y), which is a real external write.
        is_write = _is_write_target(command, m.start())
        if network and not is_write:
            continue
        external = tok
        ext_is_write = is_write
        break
    if external is None:
        return None
    # Under `read` level an external READ is allowed; refuse only when the EXTERNAL TOKEN ITSELF is a
    # write target — NOT when any write verb appears elsewhere (`grep /etc/hosts > local.txt` reads the
    # external file but writes LOCALLY, and must pass; the old whole-command _WRITE_VERB scan false-refused
    # it as "Writing", also misnaming the action).
    if level == "read" and not (ext_is_write or _MUTATING_VERB.search(command)):
        return None
    return _refusal("Writing/reading" if level == "none" else "Writing", external, workspace)
