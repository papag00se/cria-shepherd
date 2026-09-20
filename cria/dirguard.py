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
    r"|mvn\s+(?:-[\w=,.]+\s+)*(?:install\b|install:install-file\b)"  # shared ~/.m2 artifacts
    r"|composer\s+global\b"
    r"|(?:apt|apt-get|dnf|yum|pacman|apk|brew)\s+(?:install|add)\b"
    r")", re.IGNORECASE)

# The same command made workspace-local. TWO shapes, and only two: an interpreter or pip run from a
# path inside the project (`./.venv/bin/pip`, a venv activated in the same line), or an explicit
# DESTINATION flag whose VALUE is a path inside the project.
_LOCAL_INSTALL_VENV = re.compile(
    r"(?:^|[\s;&|(])\.{0,2}/?[\w.-]*(?:venv|env|virtualenv)[\w.-]*/bin/"   # ./.venv/bin/pip …
    r"|(?:^|[\s;&|(])(?:source|\.)\s+\.{0,2}/?[\w.-]*(?:venv|env)[\w.-]*/bin/activate",
    re.IGNORECASE)

# WHICH FLAG MEANS "PUT IT HERE" IS A FACT ABOUT THE MANAGER, not about the letter. This was one
# alternation of eight spellings applied to every manager at once, and it tested SPELLING rather
# than DESTINATION — which its own note two commits ago said was the bug, in those words. Run
# against the previous rule:
#
#   pip install -i https://pypi.org/simple flask   ALLOWED   (-i is pip's --index-url; the install
#                                                             still lands in shared site-packages)
#   apt-get install -y vim --root x                ALLOWED
#   cargo install --path .                         ALLOWED   (--path is cargo's SOURCE; the binary
#                                                             goes to ~/.cargo/bin)
#   pip install -t ./libs requests                 REFUSED   (pip's own --target short form)
#
# And the mirror image, live at 20260823T032555 call 0040: the coder ran
# `gem install countries --user-dir <the workspace>` and was told "an install must land inside the
# project directory (<the same path>), and this one would not."
#
# A manager with no project-local destination — apt, dnf, yum, pacman, apk, brew — is absent on
# purpose: there is no flag that makes a system install local, so none is accepted.
_DEST_FLAGS = (
    (re.compile(r"\b(?:pip|pip3|python3?\s+-m\s+pip)\b", re.I), ("--target", "-t", "--prefix", "--root")),
    (re.compile(r"\bgem\b", re.I), ("--install-dir", "-i", "--bindir", "-n")),
    (re.compile(r"\bbundle\b", re.I), ("--path",)),
    (re.compile(r"\bcomposer\b", re.I), ("--working-dir", "-d")),
    (re.compile(r"\b(?:npm|pnpm|yarn)\b", re.I), ("--prefix",)),
    (re.compile(r"\bcargo\b", re.I), ("--root",)),      # --path is the SOURCE, not the destination
    (re.compile(r"\bgo\b", re.I), ()),                   # GOBIN is an env var, not a flag
)


def _flag_value(command: str, flag: str) -> str | None:
    """The value given to ``flag``, or None when the flag is absent or has none."""
    m = re.search(r"(?:^|\s)" + re.escape(flag) + r"(?:=|\s+)([^\s;&|]+)", command)
    return m.group(1) if m else None


def _lands_in_the_project(value: str, workspace: str | None) -> bool:
    """Is this destination inside the workspace? A URL is not a destination at all — which is the
    whole of pip's `-i https://pypi.org/simple`, the flag that used to wave a global install through.

    ONE OWNER for the containment question: :func:`is_external`, the same lexical answer every other
    guard here uses. A relative value resolves against the workspace and is internal by that rule."""
    if not value or "://" in value:
        return False
    return not is_external(value, workspace)


def _installs_into_the_project(command: str, workspace: str | None) -> bool:
    """The install names a destination inside the project — the ONE thing that makes a
    shared-by-default manager ordinary workspace work."""
    if _LOCAL_INSTALL_VENV.search(command):
        return True
    for manager, flags in _DEST_FLAGS:
        if not manager.search(command):
            continue
        for flag in flags:
            value = _flag_value(command, flag)
            if value is not None and _lands_in_the_project(value, workspace):
                return True
    return False


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
    if _installs_into_the_project(command, workspace):
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
                and not _installs_into_the_project(command, None))


def _tool_present(name: str) -> bool:
    """Is this tool on PATH right now? The one question that separates a real route from a guess.

    On the CODER's path, not cria's: this advice is a sentence telling the coder which command to
    run, so the only PATH that can make it true is the one the coder's commands use. cria's service
    PATH has none of the user's toolchains, which turned every route through them into "no route"
    (#5b — see :mod:`cria.toolpath`).

    A BOOL VIEW OF A THREE-VALUED ANSWER, and both of the falsy values mean "do not build a route on
    this": `""` is "their shell resolves nothing" and None is "nobody has asked". The caller that
    needs to tell those apart asks `_resolved_tool` directly (#23c)."""
    return bool(_resolved_tool(name))


def _resolved_tool(name: str) -> str | None:
    """The name the coder must actually TYPE for this tool: the resolved name, "" when their
    shell resolves nothing, and None until anybody has asked.

    The plain name when the coder's shell resolves it, otherwise the versioned executable that does
    — distros version the binary rather than the package (`bundle3.2`, `python3.12`, `pip3`), and
    asked name-exactly cria once concluded "ruby has no project-local route" while `bundle3.2` was on
    PATH the whole time. Keeping the resolved answer is what stops cria selecting a route on the
    strength of `bundle3.2` and then telling the coder to run `bundle` (#5b).

    THREE-VALUED, AND IT STAYS THAT WAY. `toolpath.resolved` answers a name, `""` when the coder's
    shell resolves nothing, and **None** until anybody has asked — and this used to end
    `return got or None`, folding the last two together. Naming a command on an unanswered question
    is the false fact the whole route-selection exists to avoid (#3), and so is telling a coder there
    is no route when the question has simply not come back yet (#23c). The caller needs both."""
    return toolpath.resolved(name)


def _local_install_advice(command: str) -> str:
    """The project-local route for the manager that was actually refused, or "" when there is none.

    An empty string is a real answer, and for two reasons. apt, dnf, brew and pacman install to the
    machine and have no project-local form. And an ecosystem whose tools were ASKED about and are
    not installed has no route cria can honestly offer either — better to state only what is
    forbidden than to send the coder after a command that cannot run (#3, #5b).

    A THIRD STATE, WHICH USED TO RENDER AS THE SECOND. The tools are discovered by asking the
    workspace view, which answers None until a survey lands — so early in a session nothing is
    known, and silence there reads as "this cannot be done". At 20260823T032555 the first NINE
    install refusals in one coder prompt were routeless and the tenth onward had a route; the
    escalation reasoner then read those nine and told the coder to hardcode the data the gem would
    have provided, while `countries (8.1.0)` sat installed on the box and
    `gem install --install-dir vendor/bundle countries` passed this very guard. 580 of 3,704
    renderings (16%) are routeless. Unanswered now says so (#23c).

    THE ROUTE NAMES THE BINARY THAT WAS ACTUALLY FOUND. `_tool_present` answers a bool, so the route
    used to be selected on the strength of `bundle3.2` and then printed with the literal `bundle` —
    which does not exist on this box. Measured on shipping-rates-rb × ternary-bonsai, cycle 2: ten
    refusals, all naming `bundle install --path vendor/bundle`, calls 0037–0057 spent on installs
    that could not succeed, collapsing the run. The coder never tried `bundle3.2` because nothing named it.
    That is the same #5b failure the header of `install_remedy.txt` already records as fixed twice:
    the DISCOVERY was repaired and the SENTENCE was left behind. Now the discovered name is filled
    into the route's `{{TOOL}}` token, so the two can no longer disagree."""
    routes = prompts.load_map("install_remedy")
    for pat, options in _INSTALL_REMEDY:
        if not pat.search(command):
            continue
        unanswered = False
        for key, needs in options:
            # THREE-VALUED, NOT TWO. `toolpath.resolved` answers a name, "" for "this shell resolves
            # nothing", and None for "nobody has asked yet" — and collapsing the last two is what
            # turns a question into "there is no way to do this here". Kept apart so the fall-through
            # below can say which of the two happened (#23c).
            raw = {t: _resolved_tool(t) for t in needs}
            unanswered = unanswered or any(v is None for v in raw.values())
            found = {t: (v or None) for t, v in raw.items()}
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
        # THIS ECOSYSTEM HAS ROUTES AND NOT ONE OF THEM COULD BE CONFIRMED. That is three-valued:
        # "there is no way to do this here" (apt, brew — the branch below) is a different fact from
        # "the way has not been established yet", and both used to render as silence.
        #
        # It matters because the answer arrives LATE. `_resolved_tool` asks the workspace view, which
        # queues the question for the next survey and answers None until one lands — and a survey
        # rides only on a composed write/edit/list or on a gate, so a coder stuck in a loop of raw
        # `gem install` shell commands triggers none. Measured at 20260823T032555: the first NINE
        # install refusals in coder prompt 0084 carried no route at all and the tenth onward did;
        # 580 of 3,704 renderings across the corpus (16%) are routeless. Then the refusal escalation
        # read those nine and authored: "Stop trying to install the countries gem — it cannot be
        # installed in this sandbox … Replace the require with a hardcoded set of EU two-letter
        # codes." `countries (8.1.0)` is installed on this box and
        # `gem install --install-dir vendor/bundle countries` passes this very guard.
        #
        # Saying "not established yet" costs one clause and denies that conclusion its premise (#23c).
        if unanswered and routes.get("route_unknown_yet"):
            return " " + routes["route_unknown_yet"]
        return ""      # every route was ASKED about and none of its tools is here (#3, #5b)
    return ""      # the ecosystem installs to the machine and has no project-local form (#3)


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
        # A BARE PACKAGE NAME, not a path that happens to start with the tool's letters. `\w*` let
        # `gems/europe-0.0.28.gem` match `gem` + `s`, so cria answered `gem install --local
        # gems/europe-0.0.28.gem` with "gems is already installed on this machine — the executable is
        # named `gem`, so type that instead of `gems`. You do not need to install it." There is no
        # package called `gems`; the coder had typed a FILE PATH. Walked on shipping-rates-rb x
        # nemotron-elastic 1787465385, and the model spent the next eight calls on installs (#5b).
        m = re.search(rf"install\s+(?:--?\S+(?:=\S+)?\s+)*({re.escape(stem)}\w*)(?![\w./-])",
                      command, re.I)
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
    Together with the parameter-value case that is 492 of 1,242 captured refusals.

    A GLOB IS THE SAME SHAPE. `*` is excluded from the path-token character class, so it TERMINATES
    the token before it and the remainder starts at the following `/` — which then reads as rooted.
    `ls vendor/bundle/ruby/*/gems/countries/lib/` was refused with "The path '/gems/countries/lib/'
    is outside it", a path the coder never wrote, about a directory inside its own workspace.

    Walked on shipping-rates-rb x ternary-bonsai 1787471013: the gem had installed to vendor/bundle,
    the coder probed its API from memory, got two NameErrors, correctly decided to go and read the
    gem's source — and cria refused that three times, on this. At 0038 it concluded "maybe I should
    just use a simpler gem or embed the EU list directly" and wrote `Countries.new(code)` from
    memory, which is the four-error NoMethodError the cell scored on. cria did not merely fail to
    help here; it closed the one route to the answer, with a false statement (#5b, #11b)."""
    i = start - 1
    if i < 0:
        return False
    if command[i] == "*" or (i > 0 and command[i] == "/" and command[i - 1] == "*"):
        return True
    if command[i] not in ")}":
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


# Package-manager dependency caches: the read-only artifact stores an installed dependency resolves
# into. A model grounding a library's REAL api (javap a jar, read a wheel/crate/module source) must
# reach these — they hold public library files, never the project's own code and never secrets.
# Matched at the ARTIFACT subtree ONLY, never the manager's config root, so credential files
# (~/.m2/settings.xml, ~/.cargo/credentials.toml, ~/.gem/credentials, ~/.npmrc) stay refused. A READ
# here writes nothing outside the workspace and is allowed even at ``none``; a WRITE into a cache is a
# different act — it corrupts a machine-shared store (the eaf480f leak class) — and still falls
# through to refusal (only ``write`` permits it). Walked: feed-pipeline-java x ornith15 1788684045
# hallucinated the OpenCSV 5.9 API across 50+ turns and never compiled, because cria's own steer told
# it to "inspect its jar in your local Maven cache" and then refused every read of the resolved
# opencsv-5.9.jar under ~/.m2/repository.
_DEP_CACHE_MARKERS = (
    "/.m2/repository/",       # Maven / Gradle artifacts (not ~/.m2/settings.xml)
    "/.gradle/caches/",       # Gradle
    "/.cargo/registry/",      # Rust crates (not ~/.cargo/credentials.toml)
    "/.cargo/git/",
    "/go/pkg/mod/",           # Go module cache (read-only by design)
    "/site-packages/",        # Python installed packages
    "/dist-packages/",
    "/gem/ruby/",             # Ruby gems: ~/.gem/ruby/, ~/.local/share/gem/ruby/ (not ~/.gem/credentials)
    "/ruby/gems/",            # Ruby gems: /usr/lib/ruby/gems/, rbenv/rvm, bundler .../ruby/gems/
    "/node_modules/",         # Node packages: any node_modules holds public JS source, never secrets
)


def _is_dependency_cache(path: str) -> bool:
    """True when ``path`` is inside a package manager's read-only dependency-artifact cache — the
    ground truth for an installed dependency's API. The artifact subtree only, so a manager's
    credential-bearing config root is never matched."""
    if not path or not path.strip():
        return False
    p = os.path.normpath(os.path.expanduser(path.strip())) + "/"
    return any(marker in p for marker in _DEP_CACHE_MARKERS)


# The package-manager cache ROOTS (~/.m2, ~/.gradle, ~/.cargo, ~/go/pkg) whose ARTIFACT subtree cria
# DOES allow to be read (_DEP_CACHE_MARKERS above). A read of the ROOT itself — `find ~/.m2` to
# discover the cache layout, or a stray settings.xml — stays refused (the root holds the manager's
# credential/config files), but a bare "outside the workspace" makes a weak model infer it is OFFLINE
# and abandon the network entirely. Walked: feed-pipeline-java x ornith15 1788933193 ran `find ~/.m2`,
# drew the plain refusal, reasoned "there's likely NO network access" and burned ~5 early turns
# hand-building a scratch ./tmp/m2repo and guessing unresolvable OpenCSV versions — while the network
# was fine (it downloaded opencsv 5.8 the same session). Naming the readable artifact subtree, and
# that this is a PATH limit and not a network one, is the sentence that ends that rabbit hole. This is
# the reader-facing complement of a00ce45 (which allowed the artifact subtree itself): same jar, same
# task, the layer up. Covers all six battery languages (Maven/Gradle, Cargo, Go, Python, Ruby, Node);
# each entry's named subtree is one the read-allow markers above actually permit, so the note can
# never point a model at a location a read would refuse (#5b).
_DEP_CACHE_ROOTS = (
    ("/.m2/", "~/.m2/repository"),
    ("/.gradle/", "~/.gradle/caches"),
    ("/.cargo/", "~/.cargo/registry"),
    ("/go/pkg/", "~/go/pkg/mod"),
    ("/lib/python", "its site-packages/ subdirectory"),
    ("/.gem/", "~/.gem/ruby (the installed gem sources)"),
    ("/.npm/", "any node_modules/ directory (the project's, or the global one shown by `npm root -g`)"),
)


def _dep_cache_root_hint(path: str) -> str:
    """The readable artifact subtree (e.g. ``~/.m2/repository``) when ``path`` sits inside a package
    manager's cache tree — else "". Only reached from ``_refusal`` for an already-REFUSED path, so it
    names the cache ROOT or a credential sibling, never the allowed artifact subtree (which
    ``path_refusal``/``command_refusal`` clear before any refusal is built)."""
    if not path or not path.strip():
        return ""
    p = os.path.normpath(os.path.expanduser(path.strip())) + "/"
    for marker, subtree in _DEP_CACHE_ROOTS:
        if marker in p:
            return subtree
    return ""


# `/1_000_000` in `cents /1_000_000` is integer division, not a filesystem path: a single rooted
# token that is ALL digits/underscores (with an optional decimal part), a shape no real path uses.
# The path-token scan grabs it because a space precedes the `/`. Walked: feed-pipeline-java x
# ornith15 1788907072 drew 11 "The path '/1_000_000' is outside it" refusals on a Java milli-cent
# literal in a heredoc, which fed a false "the workspace was reset" belief that recharged the model's
# verification loop. Same class as the quoted-pattern and URL-fragment false-positives already fixed.
_NUMERIC_LITERAL = re.compile(r"^/\d[\d_]*(?:\.[\d_]+)?$")


def _is_numeric_literal(tok: str) -> bool:
    """True for a rooted arithmetic literal like ``/1_000_000`` or ``/3.14`` — never a real path."""
    return bool(_NUMERIC_LITERAL.match(tok))


def _typo_fold(s: str) -> str:
    """Case-fold and collapse dash/underscore — the two one-glyph workspace-typo classes walked so
    far. Anything looser would start matching genuinely different directories."""
    return os.path.normpath(os.path.expanduser(s.strip())).lower().replace("_", "-")


def _within_one_edit(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` differ by at most ONE insertion, deletion, substitution or
    transposition of adjacent characters. Damerau-Levenshtein distance <= 1, decided without
    building a matrix: the lengths bound the shape, so each case is a single scan."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:                                   # substitution or transposition
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (len(diff) == 2 and diff[1] == diff[0] + 1
                and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    long, short = (a, b) if la > lb else (b, a)    # one insertion / deletion
    i = 0
    while i < len(short) and long[i] == short[i]:
        i += 1
    return long[i + 1:] == short[i:]


def _case_typo_of_workspace(path: str, workspace: str | None) -> bool:
    """True when ``path`` IS the workspace (or a path under it) up to ONE TYPED GLYPH — i.e. the
    model typed its own project directory wrong by a single character.

    Walked on ada-handles_gemma4_codex_poff_1785869053: the coder wrote ``…-8Ibs7re8`` (capital I)
    for its real ``…-8ibs7re8`` workspace 106 times, drew this refusal 50+ times — the message
    printed both strings side by side, and a temp-0 12B never spotted the one-letter difference;
    it invented "absolute paths are forbidden" and spiralled ~300 calls. Hours after the case fix,
    ada-handles_mellum2_codex_poff_1785880114 hit the SAME loop one glyph over: ``suite-ada_handles``
    (underscore) for ``suite-ada-handles`` — the note never fired because the fix was
    letter-case-only. The comparison is exact ground truth cria already holds; naming the
    difference is the one sentence that ends the loop at its first firing.

    THIRD INSTANCE, and the reason this no longer enumerates glyph classes. L5
    shipping-rates-rb x nemotron-elastic (1787754910) typed ``…-zpis1_t`` for its real ``…-zpsis1_t``
    — a DROPPED letter, which neither case-folding nor dash/underscore collapsing can see. It drew
    this refusal on 42 of its 115 coder calls, from the second call to the last, and scored 8.
    Case, dash/underscore and a dropped/doubled/transposed character are all the same event — one
    mistyped glyph — so the test is now one edit on the segment that should have been the workspace,
    which covers every class of them and any fourth nobody has walked yet. Bounded to a sibling of
    the real workspace (same parent, one edit in the name) so a genuinely different directory two
    levels away can never draw the note."""
    if not workspace:
        return False
    p, ws = _typo_fold(path), _typo_fold(workspace)
    if p == ws or p.startswith(ws + os.sep):
        return True
    ws_parent, ws_name = os.path.split(ws)
    # Walk the path's own ancestors: the typo'd segment may be the whole path (`list_dir <typo>`)
    # or an ancestor of it (`read_file <typo>/Gemfile`), and both drew this refusal in the walk.
    cur = p
    while cur and cur != os.sep:
        parent, name = os.path.split(cur)
        if parent == ws_parent and _within_one_edit(name, ws_name):
            return True
        cur = parent
    return False


def _refusal(verb: str, path: str, workspace: str | None = None) -> str:
    # prompts/external_path_refusal.txt — {{PATH}} takes the quoted repr, matching the old f"{path!r}".
    # {{ROOT}} names the ACTUAL project directory when known: the anonymous "the project directory"
    # left a blocked model inventing roots (/tmp/src, /tmp/project) for whole runs — the refusal is
    # the one place cria can state the real one.
    root = f" ({workspace})" if workspace else ""
    if _case_typo_of_workspace(path, workspace):
        note = prompts.load("external_path_case_note")
    else:
        # A refused package-manager cache root (~/.m2, ~/.gradle, ...) draws the offline-misdiagnosis
        # note: the artifact subtree IS readable and this is not a network limit.
        subtree = _dep_cache_root_hint(path)
        note = (prompts.fill(prompts.load("external_path_depcache_note"), subtree=subtree)
                if subtree else "")
    return prompts.fill(prompts.load("external_path_refusal"), verb=verb, path=repr(path), root=root,
                        casenote=note)


def path_refusal(path: str, is_write: bool, level: str, workspace: str | None) -> str | None:
    """The refusal for a synthetic file tool's EXPLICIT path, or None when allowed. read_file/list_dir
    are reads; write_file/edit_file are writes."""
    if level == "write" or _exempt(path) or not is_external(path, workspace):
        return None
    # A READ of a dependency-artifact cache is grounding, not exfiltration — allowed at every level.
    # A WRITE into it is refused unless the operator chose `write` (falls through below).
    if not is_write and _is_dependency_cache(path):
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
        # `n /1_000_000` is integer division, not a path outside the workspace.
        if _is_numeric_literal(tok):
            continue
        if not is_external(tok, workspace) or _exempt(tok):
            continue
        # A READ of a dependency-artifact cache grounds an installed library's real API (javap a jar,
        # read a module's source); it writes nothing outside the workspace, so allow it even at
        # `none` and keep scanning for a MORE serious external token. A WRITE targeting the cache is
        # not skipped — it falls through and is refused.
        if _is_dependency_cache(tok) and not _is_write_target(command, m.start()):
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
