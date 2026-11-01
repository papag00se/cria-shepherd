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
import shlex
from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple

from . import bodykeys, probediscovery, prompts, shellinput, toolpath

LEVELS = ("none", "read", "write")

# Absolute or ~-anchored FILE path tokens in a shell command. The lookbehind rejects a `/` that
# follows a word char, dot, COLON, or SLASH — so RELATIVE paths (`a/b`, `./x`, `.venv/bin`) AND URLs
# (`https://host/path`, `//host`) are NOT matched; only a rooted single-`/...` or `~/...`. This guard
# governs the FILESYSTEM, never the network — a `curl https://…`/`wget` must never be mistaken for an
# external file access. The token ends at whitespace or a shell metacharacter.
_PATH_TOKEN = re.compile(r"(?<![\w.:/])(?:~/|~(?=[\s;&|)<>]|$)|/(?!/))[^\s'\";|&><()`$*]*")
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
# the path is preceded by a `>`/`>>`/`>|` redirect or a `-o`/`-O`/`--output`/`tee` (so `curl … -o /etc/x` and
# `curl … > /tmp/y` are still caught, but a URL path in the request is not).
# What the network tool SENDS from a file — `--data @/x`, `-F f=@/x`, `--data-urlencode n@/x`, `-T /x`, `--upload-file /x` — is a
# read of that file, not a URL fragment: the exemption never covers it.
_UPLOAD_BEFORE = re.compile(r"(?:@|(?:^|\s)(?:-T|--upload-file)(?:\s+|=))$")
_WRITE_TARGET_BEFORE = re.compile(r"(?:>>?\|?|(?:^|\s)-[oO]|(?:^|\s)--output|(?:^|\s)tee)\s*$")

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
_NAME_KILLERS = frozenset({"pkill", "killall", "skill"})
# What a kill is REACHED THROUGH. Each wrapper runs the command that follows it; the table says which of its
# flags take a separate operand (`sudo -u root`, `timeout -s KILL`) and how many positional operands come
# before the command (`timeout 5`). A finite grammar fact about where the command word sits, nothing more.
_KILL_WRAPPERS = {
    "sudo": (frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "--user", "--group", "--host"}), 0),
    "doas": (frozenset({"-u", "-C"}), 0),
    "env": (frozenset({"-u", "-C", "--unset", "--chdir"}), 0),
    "timeout": (frozenset({"-s", "-k", "--signal", "--kill-after"}), 1),
    "nohup": (frozenset(), 0), "time": (frozenset({"-f", "-o", "--format", "--output"}), 0),
    "command": (frozenset(), 0), "builtin": (frozenset(), 0), "exec": (frozenset({"-a"}), 0),
    "nice": (frozenset({"-n", "--adjustment"}), 0), "setsid": (frozenset(), 0),
    "stdbuf": (frozenset({"-i", "-o", "-e"}), 0), "ionice": (frozenset({"-c", "-n", "-p", "-P", "-u"}), 0),
    "xargs": (frozenset({"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter"}), 0),
    "pkexec": (frozenset({"--user"}), 0),
    "run0": (frozenset({"-u", "-g", "-D", "--user", "--group", "--chdir", "--unit", "--property", "--slice", "--nice", "--setenv",
                         "--description", "--background", "--machine"}), 0),
}
_KILL_DEPTH = 6


def _program_name(word: str) -> str:
    """The program a command word names: bare, or by a system directory (`/usr/bin/pkill`); anything else
    (`./pkill`, `/opt/x/pkill`) is some other program and keeps its whole spelling."""
    return os.path.basename(word) if os.path.dirname(word) in _SYSTEM_PROGRAM_DIRS or not os.path.dirname(word) else word


def _wrapped_command(words: list[str]) -> list[str]:
    """The command a segment really runs, for the kill reader and the root-delete reader: the lead words `_command_words` skips, plus
    each wrapper in `_KILL_WRAPPERS` with the operands ITS flags take. `command -v X` / `command -V X` only
    look X up, so they run nothing."""
    while words:
        word = words[0]
        name = _program_name(word)
        if word in _SHELL_RESERVED_LEAD or re.match(r"^\w+=", word):
            words = words[1:]
        elif name in _KILL_WRAPPERS:
            takes, positional = _KILL_WRAPPERS[name]
            words = words[1:]
            while words and words[0].startswith("-") and words[0] != "-":
                if name in ("command", "builtin") and words[0] in ("-v", "-V"):
                    return []
                flag = words[0]
                words = words[(2 if flag in takes else 1):]
                if flag == "--":
                    break
            words = words[positional:]
        else:
            break
    return words


def _shell_body(args: list[str]) -> str | None:
    """The script a `bash -c '…'` / `sh -lc '…'` call carries (the first operand after the option cluster
    that holds `c`)."""
    for i, arg in enumerate(args):
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            rest = [a for a in args[i + 1:] if not a.startswith("-")]
            return rest[0] if rest else None
        if not arg.startswith("-"):
            return None
    return None


def _unescaped(body: str) -> str:
    """A `bash -c "kill \\$(pgrep x)"` body as the inner shell reads it: the lexer keeps the backslash that
    guarded the `$` or backtick from the OUTER shell."""
    return re.sub(r"\\([$`])", r"\1", body)


def _kills_by_selector(words: list[str], marks: str) -> bool:
    """Is this ONE command (wrappers already removed) a kill whose selector is unbounded?"""
    if not words:
        return False
    name, args = _program_name(words[0]), words[1:]
    if name in _NAME_KILLERS:
        return True
    if name == "fuser":
        return any(a == "-k" or (a.startswith("-") and not a.startswith("--") and "k" in a) for a in args)
    if name == "kill":
        return any(m in a for a in args for m in marks)        # kill $(lsof …) / kill `pgrep …`: the substitution IS the selector
    return False


def _kill_in_script(script: str) -> bool:
    """Does any COMMAND in this script kill by an unbounded selector? See `_judge_commands` for what is walked."""
    return bool(_judge_commands(script, lambda words, marks, _targets: _kills_by_selector(words, marks)))


def _judge_commands(script: str, judge, depth: int = 0, inherited: str = ""):
    """The first truthy ``judge(words, marks, targets)`` over every COMMAND in this script (each segment's
    command word, through wrappers, `bash -c` bodies, `find -exec`, `eval` and command substitutions), else None.
    ``words`` has its wrappers removed; ``marks`` are the placeholder characters standing for a substitution
    (`kill $(pgrep x)` reaches the judge as `kill <mark>`); ``targets`` are the segment's write targets and
    redirect outputs. A bounded backstop: a command word that is only an argument (`echo pkill -f x`,
    `grep pkill file`, `man kill`) is prose and is admitted. Text it cannot tokenize is not judged here:
    `command_refusal` refuses it as unproven at the levels that judge paths."""
    if depth > _KILL_DEPTH:
        return None
    layout = shellinput.layout(script)          # a heredoc body is data, in a substitution body as at the top
    if layout.error:
        return None
    script = layout.shell
    subs, unknown = shellinput.expansions(script, shell=True)
    if unknown:
        return None
    for sub in subs:
        found = _judge_commands(sub.text(script), judge, depth + 1)
        if found:
            return found
    mark = next((chr(c) for c in range(0xE000, 0xF8FF) if chr(c) not in script and chr(c) not in inherited), "\ue000")
    marks = inherited + mark
    flat, last = [], 0
    for sub in subs:
        flat.append(script[last:sub.start])
        flat.append(mark)
        last = sub.end
    flat.append(script[last:])
    commands = _input_commands("".join(flat), unwrap=False)
    if commands is None:
        return None
    for _s, _e, words, targets, _inputs in commands:
        words = _wrapped_command(words)
        found = judge(words, marks, targets)
        if found:
            return found
        if not words:
            continue
        name, args = _program_name(words[0]), words[1:]
        bodies = []
        if name in _SHELLS or name in ("su", "eval"):
            body = " ".join(args) if name == "eval" else _shell_body(args)
            bodies.append(body)
        elif name == "find":
            for i, arg in enumerate(args):
                if arg in ("-exec", "-execdir", "-ok", "-okdir"):
                    run = []
                    for word in args[i + 1:]:
                        if word in (";", "+"):
                            break
                        run.append(word)
                    found = judge(_wrapped_command(run), marks, [])
                    if found:
                        return found
        for body in bodies:
            found = body and _judge_commands(_unescaped(body), judge, depth + 1, marks)
            if found:
                return found
    return None


def kill_refusal(command: str, level: str) -> str | None:
    """The refusal for a kill whose SELECTOR is unbounded, or None. Allowed at ``write``, the level
    that means the operator accepted an unrestricted process.

    Deliberately NOT a security control — the same best-effort posture as the rest of raw-shell
    handling, and the same reason: a weak model reaching past the workspace usually does it by
    accident, and the cheapest fix is to say so at the moment it happens.

    Judged per COMMAND WORD, not by a pattern over the text. Seen: `pkill`/`killall`/`skill`, `fuser -k`,
    and a `kill` whose operand is a command substitution, reached through the wrappers in `_KILL_WRAPPERS`,
    `bash -c`/`sh -c`/`su -c`/`eval` bodies, `if … then`, `find -exec` and substitutions. NOT seen: a kill
    behind a function, a sourced or saved script, `ssh host pkill`, `docker exec c pkill`, `watch pkill`,
    `parallel`, a wrapper that is not in the table, or a pid list built in a variable (`kill $PIDS`)."""
    if level == "write" or not command:
        return None
    if not _kill_in_script(command):
        return None
    return prompts.load("pattern_kill_refusal")


# MACHINE-WIDE AND REMOTE HARM: commands whose damage is not to a PATH at all, so no permission level about
# directories can describe it. Each one takes down something every other process, person or session on this
# machine depends on, or destroys work outside the machine. Refused at EVERY level, like root deletion: `write`
# means the operator accepted external file access, not losing the desktop, the disk or a remote repository.
#
# MEASURED, 2026-10-31: an evasion probe executed `kill -9 -1` through `bash -c`. The builtin signalled every
# process the user owned: the compositor, the agent host and every agent on the machine. The desktop stayed
# black until a hardware reset. An earlier incident deleted every file on the machine. `kill_refusal` admitted
# `kill -9 -1` at every level: it judges selectors (`pkill`, `kill $(pgrep …)`), and `-1` is a literal operand.
#
# Judged per COMMAND WORD through `_judge_commands` (wrappers, `bash -c`, `eval`, `find -exec`, substitutions)
# plus the exec calls of interpreter one-liners. Read-only forms of the same tools (`fdisk -l`, `parted … print`,
# `systemctl status`, `ip link show`, `iptables -L`, `crontab -l`, `kill <pid>`) are admitted. Not seen, as for
# the kill reader: a function body, a saved or sourced script, `ssh host …`, a wrapper outside `_KILL_WRAPPERS`.
_BLOCK_DEVICE = re.compile(r"^/dev/(?:sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+(?:n\d+)?|mmcblk\d+|dm-\d+|md\d+|loop\d+"
                           r"|zram\d+|root|mapper/.+|disk/.+)(?:p?\d+)?$")
_SYSTEM_TREES = frozenset({"/", "/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/var", "/boot", "/opt", "/home", "/root"})
_ACCOUNT_FILES = ("/etc/passwd", "/etc/shadow", "/etc/group", "/etc/gshadow", "/etc/fstab", "/etc/crypttab",
                  "/etc/sudoers", "/etc/sudoers.d", "/boot", "/efi", "/proc/sysrq-trigger", "/sys/power/state")
_SESSION_PROCESSES = frozenset({"hyprland", "sway", "niri", "gnome-shell", "kwin_wayland", "kwin_x11", "plasmashell", "xorg",
                                "xwayland", "sddm", "gdm", "lightdm", "greetd", "systemd", "init", "uwsm", "dbus-daemon",
                                "dbus-broker", "systemd-logind", "paseo", "paseo.bin", "sshd", "networkmanager", "tailscaled"})
_CRITICAL_UNITS = ("*.target", "*.mount", "*.swap", "display-manager*", "sddm*", "gdm*", "lightdm*", "greetd*", "systemd-logind*",
                   "dbus*", "networkmanager*", "systemd-networkd*", "systemd-resolved*", "wpa_supplicant*", "iwd*", "sshd*",
                   "ssh.*", "tailscaled*", "nordvpnd*", "user@*", "user-runtime-dir@*", "paseo*", "cria*", "systemd-journald*")
_CRITICAL_PACKAGES = re.compile(r"^(?:linux(?:-[\w.-]+)?|glibc|libc6|systemd|base|sudo|pacman|apt|dpkg|bash|coreutils|filesystem|"
                                r"util-linux|grub|limine|efibootmgr|mkinitcpio|cryptsetup|btrfs-progs|networkmanager|openssh|"
                                r"hyprland|uwsm|sddm|nvidia[\w-]*|mesa)$", re.IGNORECASE)
_POWER_VERBS = frozenset({"reboot", "poweroff", "halt", "kexec", "soft-reboot", "suspend", "hibernate", "hybrid-sleep",
                          "suspend-then-hibernate", "sleep"})
_SYSTEMCTL_VALUE_OPTS = frozenset({"-t", "--type", "-p", "--property", "-H", "--host", "-M", "--machine", "-s", "--signal",
                                   "--kill-whom", "--kill-value", "-n", "--lines", "-o", "--output", "--state", "--root",
                                   "--when", "--message", "--job-mode", "--what", "--timestamp"})
_ALL_MATCHING_PATTERNS = frozenset({"", ".", ".*", ".+", "^", "$", "^.*", "^.*$", "*"})
_EXEC_CALL = re.compile(r"(?:os\.system|os\.popen|subprocess\.\w+|Popen|check_output|check_call|execSync|execFileSync|execFile|exec|"
                        r"spawnSync|spawn|system|qx)\s*\(\s*(\[[^\]]*\]|(['\"]).*?(?<!\\)\2)", re.DOTALL)
_STRING_LITERAL = re.compile(r"(['\"])(.*?)(?<!\\)\1", re.DOTALL)
_INTERPRETER_SIGNAL_ALL = re.compile(r"\bos\.kill\(\s*(?:-\d+|0)\s*,|\bos\.killpg\(|\bkill\s*\(?\s*['\"\w-]+\s*,\s*(?:-\d+|0)\b"
                                     r"|process\.kill\(\s*(?:-\d+|0)\b|Process\.kill\([^)]*,\s*(?:-\d+|0)\s*\)")
_INTERPRETERS = re.compile(r"^(?:python[\d.]*|perl|ruby|node|nodejs|deno|bun|php)$")
_FORK_BOMB = re.compile(r"([\w:.]+)\s*\(\s*\)\s*\{[^}]*\1\s*\|\s*\1\s*&")
_SQL_DESTROY = re.compile(r"\b(?:drop\s+(?:database|schema|table)|truncate\b|dropDatabase\s*\(|flushall\b|flushdb\b)", re.IGNORECASE)


def _operands_of(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _kill_targets(args: list[str]) -> list[str]:
    """The pid operands of `kill`: after one signal option (`-9`, `-KILL`, `-s KILL`, `-n 9`) and an optional `--`."""
    if args[:1] in (["-l"], ["-L"]):
        return []
    i = 2 if args[:1] in (["-s"], ["-n"]) else (1 if args and args[0].startswith("-") and args[0] != "--" else 0)
    if args[i:i + 1] == ["--"]:
        i += 1
    return args[i:]


def _signal_all(name: str, args: list[str]) -> bool:
    if name == "killall5":
        return True
    if name == "kill":
        # `-1` is every process the caller may signal; `0` / `-N` a whole process group; `1` init; `$PPID` the caller's own host.
        return any(t in ("0", "-0", "1") or (t.startswith("-") and len(t) > 1) or "PPID" in t for t in _kill_targets(args))
    if name in ("pkill", "killall", "skill", "slay"):
        flags = ("-u", "-U", "-G", "-g", "-s", "-P", "--uid", "--euid", "--user", "--group", "--pgroup", "--session", "--parent")
        if any(a == f or (a.startswith(f) and len(f) == 2 and not a.startswith("--")) or a.startswith(f + "=")
               for a in args for f in flags):
            return True
        ops = _operands_of(args)
        return (not ops and "''" in args) or any(o in _ALL_MATCHING_PATTERNS for o in ops) or \
            any(os.path.basename(o).lower() in _SESSION_PROCESSES for o in ops)
    return False


def _systemctl_harm(args: list[str]) -> str | None:
    rest, i = [], 0
    while i < len(args):
        a = args[i]
        if a in _SYSTEMCTL_VALUE_OPTS:
            i += 2
            continue
        if not a.startswith("-"):
            rest.append(a)
        i += 1
    if not rest:
        return None
    verb, units = rest[0], rest[1:]
    if verb in _POWER_VERBS:
        return "power"
    if verb in ("isolate", "rescue", "emergency", "exit", "switch-root", "default"):
        return "session"
    if verb in ("stop", "kill", "restart", "try-restart", "reload-or-restart", "mask", "freeze", "clean") or (
            verb == "disable" and "--now" in args):
        for unit in units:
            unit = unit.lower()
            if any(c in unit for c in "*?[") or any(fnmatchcase(unit, p) for p in _CRITICAL_UNITS):
                return "session"
    return None


def _disk_harm(name: str, args: list[str]) -> bool:
    devices = [a for a in args if _BLOCK_DEVICE.match(a.split("=", 1)[-1])]
    if name == "dd":
        return any(a.startswith("of=") and _BLOCK_DEVICE.match(a[3:]) for a in args)
    if name == "cryptsetup":
        return any(v in args for v in ("luksFormat", "luksErase", "erase", "luksKillSlot", "luksRemoveKey", "reencrypt",
                                       "luksSuspend", "close", "luksClose", "remove"))
    if name in ("lvremove", "vgremove", "pvremove", "lvreduce", "wipe"):
        return True
    if name in ("zpool", "zfs"):
        return any(v in args for v in ("destroy", "labelclear"))
    if name == "mdadm":
        return any(a in args for a in ("--zero-superblock", "--stop", "-S", "--fail", "--remove"))
    if name == "btrfs":
        return any(a in ("delete", "remove") for a in args) and any(o.rstrip("/") in _SYSTEM_TREES or o == "/" for o in args)
    if not devices:
        return False
    if name.startswith("mkfs") or name in ("mke2fs", "mkswap", "mkntfs", "mkdosfs", "mkexfatfs", "blkdiscard", "shred",
                                           "ddrescue", "cp", "tee", "pv"):
        return True
    if name == "wipefs":
        return any(a in ("-a", "--all", "-o", "--offset") or a.startswith("--offset=") for a in args) and \
            not any(a in ("-n", "--no-act") for a in args)
    if name in ("fdisk", "gdisk", "cfdisk"):
        return not any(a in ("-l", "--list") for a in args)
    if name == "sfdisk":
        return not any(a in ("-l", "--list", "-d", "--dump", "-J", "--json", "-s", "--show-size", "-V", "--verify") for a in args)
    if name == "sgdisk":
        read_only = {"-p", "--print", "-i", "--info", "-v", "--verify", "-O", "--print-mbr", "-L", "--list-types", "-P", "--pretend"}
        return any(a.startswith("-") and a.split("=", 1)[0] not in read_only and not a[1:2].isdigit() for a in args)
    if name == "parted":
        return any(a in ("mklabel", "mktable", "mkpart", "rm", "resizepart", "name", "set", "toggle", "rescue", "disk_set") for a in args)
    if name == "hdparm":
        return any(a.startswith(("--security-erase", "--trim-sector-ranges", "--write-sector", "--fwdownload", "--make-bad-sector",
                                 "--dco-restore", "--security-set-pass", "--yes-i-know-what-i-am-doing")) for a in args)
    if name == "badblocks":
        return "-w" in args
    if name == "nvme":
        return any(v in args for v in ("format", "sanitize", "delete-ns", "detach-ns", "fw-download", "fw-commit", "write-zeroes",
                                       "write", "dsm"))
    return False


def _network_harm(name: str, args: list[str]) -> bool:
    words = [a.lower() for a in args]
    if name == "nmcli":
        ops = _operands_of(words)
        if ops[:2] == ["networking", "off"] or (ops[:1] == ["radio"] and "off" in ops):
            return True
        return ops[:1] in (["connection"], ["con"], ["c"], ["device"], ["dev"], ["d"]) and \
            any(v in ops[1:2] for v in ("down", "delete", "del", "disconnect"))
    if name == "ip":
        ops = _operands_of(words)
        return (ops[:2] == ["link", "set"] and "down" in ops) or (ops[:1] in (["addr"], ["address"], ["a"]) and
               ops[1:2] in (["flush"], ["del"])) or (ops[:1] in (["route"], ["r"]) and ops[1:2] in (["flush"], ["del"], ["delete"]))
    if name == "ifconfig":
        return "down" in words
    if name in ("ifdown", "rfkill"):
        return name == "ifdown" or "block" in words
    if name in ("iptables", "ip6tables", "iptables-nft", "iptables-legacy"):
        return any(a in ("-F", "--flush", "-X", "--delete-chain", "-P", "--policy") for a in args)
    if name == "nft":
        return "flush" in words or "delete" in words
    if name == "ufw":
        return any(v in words for v in ("reset", "disable"))
    if name == "tailscale":
        return any(v in words for v in ("down", "logout"))
    if name == "wg-quick":
        return "down" in words
    if name == "nordvpn":
        return any(v in words for v in ("d", "disconnect", "logout")) or ("killswitch" in words and "on" in words)
    return False


def _system_config_harm(name: str, args: list[str], targets: list[str], marks: str) -> bool:
    for target in targets:
        path = os.path.normpath(target) if target.startswith("/") else ""
        if path and any(path == p or path.startswith(p + "/") for p in _ACCOUNT_FILES):
            return True
    if name == "passwd":
        return any(a in ("-l", "--lock", "-d", "--delete", "-e", "--expire") for a in args)
    if name == "usermod":
        return any(a in ("-L", "--lock", "-e", "--expiredate", "-s", "--shell", "-l", "--login", "-u", "--uid", "-d", "--home",
                         "-G", "--groups") for a in args)
    if name in ("userdel", "deluser", "groupdel", "delgroup", "chsh", "grub-install", "vipw", "visudo"):
        return name != "visudo" or "-c" not in args
    if name == "crontab":
        return any(a in ("-r", "--remove") or (a.startswith("-") and not a.startswith("--") and "r" in a) for a in args)
    if name == "efibootmgr":
        return any(a in ("-B", "--delete-bootnum", "-o", "--bootorder", "-O", "--delete-bootorder", "-A", "--inactive",
                         "-c", "--create") for a in args)
    if name == "bootctl":
        return any(v in args for v in ("remove", "install", "update", "set-default", "unlink"))
    if name in ("chmod", "chown", "chgrp", "setfacl"):
        recursive = any(a in ("-R", "--recursive") or (a.startswith("-") and not a.startswith("--") and "R" in a) for a in args)
        return recursive and any(os.path.normpath(o) in _SYSTEM_TREES for o in _operands_of(args) if o.startswith("/"))
    if name in ("umount", "swapoff"):
        return "-a" in args or "--all" in args or any(os.path.normpath(o) in _SYSTEM_TREES for o in _operands_of(args) if o.startswith("/"))
    if name == "mount":
        ops = [os.path.normpath(o) for o in _operands_of(args) if o.startswith("/")]
        return any(a in ("--bind", "-B", "--rbind", "--move", "-M", "-o") for a in args) and bool(ops) and ops[-1] in _SYSTEM_TREES
    if name in ("pacman", "yay", "paru"):
        removing = any(a.startswith("-R") or a == "--remove" for a in args)
        return removing and any(_CRITICAL_PACKAGES.match(o) or any(m in o for m in marks) for o in _operands_of(args))
    if name in ("apt", "apt-get", "dnf", "yum", "zypper"):
        ops = _operands_of(args)
        return ops[:1] in (["remove"], ["purge"], ["autoremove"], ["erase"]) and any(_CRITICAL_PACKAGES.match(o) for o in ops[1:])
    if name in ("sysctl",):
        return any(a.startswith(("kernel.panic", "kernel.sysrq", "vm.panic_on_oom")) for a in args) and any("=" in a for a in args)
    return False


def _remote_harm(name: str, args: list[str], marks: str) -> bool:
    if name == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-C", "-c") else 1
        sub, rest = (args[i], args[i + 1:]) if i < len(args) else ("", [])
        if sub != "push":
            return False
        return any(a in ("-f", "--force", "--mirror", "--delete", "-d", "--prune") or a.startswith(("--force-with-lease", "--force-if-includes"))
                   or (a.startswith("-") and not a.startswith("--") and "f" in a)
                   or (not a.startswith("-") and (a.startswith("+") or a.startswith(":") or "+refs/" in a)) for a in rest)
    ops = _operands_of(args)
    if name == "gh":
        method = next((args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-X", "--method")), "")
        return "delete" in ops or "archive" in ops or method.upper() == "DELETE" or any(a.upper() in ("-XDELETE", "--METHOD=DELETE") for a in args)
    if name in ("aws", "gcloud", "az", "doctl", "flyctl", "fly", "heroku", "vercel", "netlify", "wrangler"):
        return (ops[:2] == ["s3", "rm"] and ("--recursive" in args or "-r" in args)) or ops[:2] == ["s3", "rb"] or \
            any(o.startswith(("delete", "terminate", "destroy", "remove")) or o in ("rm", "rb", "purge") for o in ops[1:])
    if name in ("terraform", "tofu", "pulumi", "cdk"):
        return "destroy" in ops or "-destroy" in args or "--destroy" in args
    if name in ("kubectl", "oc", "helm"):
        return any(v in ops for v in ("delete", "uninstall", "drain")) or ("scale" in ops and any("replicas=0" in a for a in args))
    if name in ("docker", "podman", "nerdctl"):
        if "prune" in ops or ops[:2] in (["volume", "rm"], ["volume", "remove"]):
            return True
        return ops[:1] in (["rm"], ["stop"], ["kill"], ["rmi"]) and any(m in a for a in args for m in marks) or \
            (ops[:1] in (["rm"], ["stop"], ["kill"]) and any(a in ("-a", "--all") for a in args))
    if name in ("psql", "mysql", "mariadb", "mongosh", "mongo", "redis-cli", "sqlcmd", "cqlsh", "clickhouse-client"):
        return any(_SQL_DESTROY.search(a) for a in args)
    return False


def _interpreter_harm(name: str, args: list[str], depth: int) -> str | None:
    """An interpreter one-liner (`python3 -c`, `perl -e`, `node -e`): its own signal-everything call, and the shell
    commands its exec calls carry (`os.system('reboot')`, `subprocess.run(['kill', '-9', '-1'])`)."""
    body = next((args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-c", "-e", "-E", "--eval", "-r")), None)
    if body is None:
        return None
    if _INTERPRETER_SIGNAL_ALL.search(body):
        return "signal_all"
    for call in _EXEC_CALL.finditer(body):
        arg = call.group(1)
        command = shlex.join(m.group(2) for m in _STRING_LITERAL.finditer(arg)) if arg.startswith("[") else arg[1:-1]
        found = _judge_commands(command, _machine_harm_judge, depth + 1) if command else None
        if found:
            return found
    return None


def _machine_harm_judge(words: list[str], marks: str, targets: list[str]) -> str | None:
    """The harm category of ONE command (wrappers already removed), or None."""
    if not words:
        return None
    name, args = _program_name(words[0]), words[1:]
    if _signal_all(name, args):
        return "signal_all"
    if name in ("shutdown", "reboot", "poweroff", "halt") or (name == "kexec" and "-e" in args) or \
            name in ("omarchy-system-reboot", "omarchy-system-shutdown", "omarchy-toggle-suspend") or \
            (name in ("telinit", "init") and any(a in ("0", "1", "6", "s", "S", "single", "rescue") for a in args)):
        return "power"
    if name == "systemctl":
        return _systemctl_harm(args)
    if name == "loginctl":
        verb = next(iter(_operands_of(args)), "")
        if verb in _POWER_VERBS:
            return "power"
        if verb in ("terminate-user", "kill-user", "terminate-session", "kill-session", "terminate-seat"):
            return "session"
        return None
    if (name == "hyprctl" and re.search(r"\bdispatch\s+exit\b", " ".join(args))) or (name == "uwsm" and "stop" in args) or \
            (name in ("swaymsg", "i3-msg") and "exit" in args) or (name == "niri" and "quit" in args) or \
            name in ("gnome-session-quit", "omarchy-system-logout") or \
            (name == "nvidia-smi" and any(a in ("-r", "--gpu-reset") for a in args)):
        return "session"
    if _disk_harm(name, args) or any(_BLOCK_DEVICE.match(t) for t in targets):
        return "disk"
    if _network_harm(name, args):
        return "network"
    if _system_config_harm(name, args, targets, marks):
        return "system_config"
    if _remote_harm(name, args, marks):
        return "remote"
    if _INTERPRETERS.match(name):
        return _interpreter_harm(name, args, 0)
    return None


def machine_harm_refusal(command: str) -> str | None:
    """The refusal for a command that would take down this machine, its session, its disks or its network, or
    destroy remote work, at ANY permission level; None otherwise. Same posture as `root_recursive_delete_refusal`:
    a bounded lexical backstop for an untrusted model, not a sandbox."""
    if not command:
        return None
    if _FORK_BOMB.search(command):
        found = "fork_bomb"
    else:
        found = _judge_commands(command, _machine_harm_judge)
    return prompts.load_map("machine_harm_refusal")[found] if found else None


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


def programs_that_ran(command: str) -> list[str]:
    """The bare program names a SUCCESSFUL exit of ``command`` proves were launched: the command word of every segment, when the
    segments form an unconditional chain (one command, or commands joined by `&&`; an exit 0 then means each ran).

    A pipeline's status is its last command's, `;` keeps only the last, and `||` may never reach its right side, so those prove
    nothing about the others and answer [] (a lookup, `command -v X`, runs nothing and is skipped by the wrapper reader). A name
    spelled as a path is some other program. Read by the workspace view: the coder's own successful `gem list` is ground truth
    that `gem` exists, which the survey that answers for programs does not supply until a write rides one."""
    if not command:
        return []
    layout = shellinput.layout(command)
    if layout.error or layout.shell != command:
        return []                                    # a heredoc or a continuation: not the plain chain this reads
    spans = [(a, b) for a, b in _segment_spans(command) if command[a:b].strip()]
    if not spans or any(command[spans[i][1]:spans[i + 1][0]].strip() != "&&" for i in range(len(spans) - 1)):
        return []
    found = _input_commands(command, unwrap=False)
    if found is None:
        return []
    names = []
    for _s, _e, words, _targets, _inputs in found:
        words = _wrapped_command(words)
        if words and "/" not in _program_name(words[0]):
            names.append(_program_name(words[0]))
    return names


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
    if command[i] == '"':
        # `"$DEC"/x.go` / `"${DIR}"/x` / `"$(go env GOMODCACHE)"/x`: a DOUBLE-quoted expansion followed by its tail. The quote
        # hides the closing `)` / `}` from the check below, and the scan then read `/x.go` as a rooted path the coder never
        # wrote ("'/' is outside the project" for `ls "$DEC"/*.go` — walked on cart-billing-go x ornith1.5_9b).
        return any(e == i and s < e and re.search(r"\$|`", command[s:e]) for s, e in _quoted_spans(command))
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


# Bash's metacharacters: a `#` that follows one of these (or opens the text) begins a COMMENT; a `#`
# anywhere else in a word (`a#c`, `$#`, `${#x}`, `\\#`, `""#x`) is data. `\r` is not one.
_COMMENT_LEAD = " \t\n;&|()<>"


def _join_continuations(command: str, *, drop_comments: bool = False) -> tuple[str, Sequence[int]]:
    """The command as the shell READS it: every backslash-newline outside single quotes removed (bash
    drops it everywhere else, inside double quotes too) — EXCEPT inside a comment, where the newline
    ends the comment whatever precedes it (`# note \\<newline>rm -rf /` is a comment and a command).
    Returns the projection and, for each of its characters, the index it came from in ``command`` —
    the original text is never altered and callers that report positions map back through the second
    value.

    One owner for this fact. `shlex` keeps the newline as a literal character of the word, so
    `cd \\<newline>..` read as a directory named "\\n.." inside the workspace while bash ran `cd ..`;
    `c\\<newline>d`, `>\\<newline>>` and `2\\<newline>>` split the same way. Quote and backslash
    ownership is the one `_unquoted_chars` uses: a backslash outside single quotes escapes the NEXT
    character, so `\\\\<newline>` is an escaped backslash and a real newline, not a continuation. A
    comment opens only at the start of a word of the text AS JOINED (so `x\\<newline># y` is the word
    `x# y`) — the opening rule `shellinput.layout` masks comments by, but with bash's own
    metacharacters (`<` and `>` open a comment, `\\r` does not), checked against real bash in the tests.
    ``drop_comments`` omits each comment's text and keeps the newline that ends it, for a caller whose own
    tokenizer would otherwise swallow that newline together with the comment."""
    if "\\" not in command and "#" not in command:
        return command, range(len(command))      # nothing to join and no comment can open: the identity
    out: list[str] = []
    origin: list[int] = []
    quote = ""
    word_start = True
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'":
            if command[i + 1:i + 2] == "\n":
                i += 2
                continue
            out.append(c)
            origin.append(i)
            if i + 1 < n:
                out.append(command[i + 1])
                origin.append(i + 1)
            word_start = False
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ""
            word_start = False
        elif c in "\"'":
            quote = c
            word_start = False
        elif c == "#" and word_start:
            end = command.find("\n", i)
            end = n if end < 0 else end
            if not drop_comments:
                out.extend(command[i:end])
                origin.extend(range(i, end))
            i = end
            continue
        else:
            word_start = c in _COMMENT_LEAD
        out.append(c)
        origin.append(i)
        i += 1
    return "".join(out), origin


def _unquoted_chars(command: str):
    """Lexical shell syntax positions, sharing quote/backslash ownership."""
    quote, escaped = "", False
    for i, c in enumerate(command):
        if escaped:
            escaped = False
            continue
        if c == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        else:
            yield i, c


def _segment_spans(command: str) -> list[tuple[int, int]]:
    """(start, end) of each shell segment — text between UNQUOTED ``; & | ( )`` and newlines — in the
    coordinates of ``command``. Judged on the text the shell reads (continuations joined), so a
    separator or redirect operator split by a backslash-newline is one token here as it is to bash."""
    text, origin = _join_continuations(command)
    at = lambda k: origin[k] if k < len(origin) else len(command)  # noqa: E731
    spans, start = [], 0
    for i, c in _unquoted_chars(text):
        if c in ";&|()\n":
            # Redirect operators are not command boundaries: keep >& / <&,
            # &> / &>> and >| intact for the shared redirection reader.
            if (c == '&' and (text[i - 1:i] in ('>', '<')
                              or text[i + 1:i + 2] == '>')):
                continue
            if c == '|' and text[i - 1:i] == '>':
                continue
            spans.append((at(start), at(i))); start = i + 1
    spans.append((at(start), len(command)))
    return spans


# WHERE THE OS KEEPS ITS PROGRAMS. A segment that RUNS one of these by its absolute path
# (`/usr/bin/time -v java …`) executes a system tool; it does not read or write that path as data, and
# it is the same act as the bare name a PATH lookup resolves (`time`, `java`), which this guard never
# judges. The guard is about another PROJECT's files, not the OS's plumbing (see _EXEMPT_PREFIXES).
# Only the command word is exempt: an argument, a redirect or a write under these directories is still
# judged like any other path, and a program run from anywhere else (another project's script) still is.
# Walked: feed-pipeline-java x ornith1.5_9b 1792474299 call 0079 — `for i in 1 2 3; do /usr/bin/time -v
# java …` was refused as "Writing/reading outside the working directory … '/usr/bin/time'" with a
# put-it-under-./tmp/ route that names nothing the coder could change (#5b); four captured sessions,
# every system-directory refusal in the corpus is this one shape.
_SYSTEM_PROGRAM_DIRS = frozenset({"/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin"})
# The text a segment may carry BEFORE its command word: shell compound keywords, `VAR=value`
# assignments and the transparent prefix commands with their flags.
_COMMAND_WORD_LEAD = re.compile(
    r"^\s*(?:(?:do|then|else|elif|!|\{)\s+)*(?:\w+=\S*\s+)*"
    r"(?:(?:sudo|env|command|nohup|time|exec|nice)\s+(?:-\S+\s+)*)*$")


def _runs_system_program(command: str, segments, start: int, tok: str) -> bool:
    """Is the rooted token at ``start`` the COMMAND WORD of its segment, naming a program in one of
    the OS's program directories? Lexical, like the rest of the scan: nothing is resolved on disk."""
    if os.path.dirname(os.path.normpath(tok)) not in _SYSTEM_PROGRAM_DIRS:
        return False
    for s, e in segments:
        if s <= start <= e:
            return bool(_COMMAND_WORD_LEAD.match(command[s:start]))
    return False


_SEGMENT_SEARCH_LEAD = re.compile(
    r"^\s*(?:\w+=\S*\s+)*(?:(?:sudo|env|time|nohup|xargs|command)\s+(?:-\S+\s+)*)*"
    r"(?:e?grep|fgrep|rg|ag|ack|sed|awk|gawk)\b", re.IGNORECASE)


def _segment_is_text_search(command: str, segments, pos: int) -> bool:
    """Is the segment containing ``pos`` itself a text-search / stream-edit command?"""
    for s, e in segments:
        if s <= pos <= e:
            return bool(_SEGMENT_SEARCH_LEAD.match(command[s:e]))
    return False


_PREFIX_WORDS = {"sudo", "env", "command", "builtin", "nohup", "time", "exec", "nice", "xargs"}
_SHELL_RESERVED_LEAD = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{"})
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_DEST_LAST = {"cp", "ln", "install", "rsync"}
_ALL_OPERANDS = {"mv", "rm", "rmdir", "touch", "mkdir", "tee", "unlink", "shred"}
_SKIP_FIRST = {"chmod", "chown", "chgrp"}


class _UnprovenWrite:
    """A write whose destination cannot be established; not an invented path."""


_UNPROVEN_WRITE = _UnprovenWrite()


class _InputRefusal:
    def __init__(self, message: str):
        self.message = message


def _shell_tokens(command: str, *, extra_wordchars: str = "") -> list[tuple[str, int, int]] | None:
    """The existing shlex words with their exact source spans, before quote removal. The spans index
    ``_join_continuations(command)[0]`` (the text the shell reads), which equals ``command`` unless it
    holds a backslash-newline; a caller comparing a span with source text compares against that."""
    command = _join_continuations(command)[0]
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    lexer.wordchars += "".join(c for c in "[]{}$,:@%+!^#=" if c not in lexer.wordchars)
    lexer.wordchars += extra_wordchars
    tokens = []
    try:
        while True:
            # shlex's punctuation lexer retains lookahead characters separately
            # from its StringIO cursor; they belong to the next token's span.
            start = lexer.instream.tell() - len(lexer._pushback_chars)
            word = lexer.get_token()
            if word is None:
                return tokens
            end = lexer.instream.tell() - len(lexer._pushback_chars)
            while start < end and command[start] in lexer.whitespace:
                start += 1
            whitespace = {start + p for p, c in _unquoted_chars(command[start:end])
                          if c in lexer.whitespace}
            while end > start and end - 1 in whitespace:
                end -= 1
            tokens.append((word, start, end))
    except ValueError:
        return None


def _is_operator(word: str, text: str, start: int, end: int) -> bool:
    """Is this ``_shell_tokens`` token (``text[start:end]`` is its source in the text the spans index)
    shell OPERATOR syntax? shlex returns a backslash-escaped `\\(` — find's grouping, `-exec … \\;` —
    as the bare word `(`, the same word a real subshell opener gives. Bash never reads a backslash-escaped
    character as an operator, in any quote state (inside quotes it is data too), so a token whose every
    character was escaped is a literal word. Quoted punctuation stays an operator to the callers that
    ask: whether a quote is really open is a fact this lexer does not share with bash in every case.
    ornith1.5_9b / Java overnight run 1 call 0014: `find <declared root> -type d \\( -iname … \\)` was
    refused as "The characters ( are read here as an operator"."""
    return (bool(word) and set(word) <= _PUNCT
            and text[start:end] != "".join("\\" + c for c in word))


def _shell_words(command: str) -> list[str] | None:
    tokens = _shell_tokens(command)
    return None if tokens is None else [word for word, _, _ in tokens]


def _is_prefix_word(word: str) -> bool:
    """A transparent prefix command, spelled bare or by its system path (`/usr/bin/env`)."""
    return word in _PREFIX_WORDS or (os.path.basename(word) in _PREFIX_WORDS
                                    and os.path.dirname(word) in _SYSTEM_PROGRAM_DIRS)


def _command_words(words: list[str]) -> list[str]:
    """The command a segment really runs. Prefix words and assignments (`builtin`, `command`, `time`,
    `env`, `/usr/bin/env`, `VAR=`), leading shell reserved words (`then`, `do`, `{`, `!` …) and bash's
    `function NAME` lead can follow one another in any order, so each is skipped repeatedly until the
    argv stops changing. A finite grammar fact about where the command word sits — not a judgment about
    which program is invoked: what a function, a sourced script or `eval` does later is out of scope.
    The ONE owner: a write target, a saved-script consumer and a directory change inside `if …; then
    CMD; fi` or `{ CMD; }` are the same command as outside it."""
    while words:
        if words[0] in _SHELL_RESERVED_LEAD:
            words = words[1:]
        elif words[0] == "function" and len(words) > 1:
            words = words[2:]
        elif re.match(r"^\w+=", words[0]):
            words = words[1:]
        elif _is_prefix_word(words[0]):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        else:
            break
    return words


def _follow_cd(words: list[str], cur: str | None) -> str | None:
    """Where a directory-changing command leaves the cwd, or None when that is not knowable here.

    An operand beginning `-` is never a literal directory: it is an option (`cd -P` with no operand
    goes HOME, as does `cd --`), or `cd -` (the inherited OLDPWD). `pushd +N` rotates the inherited
    directory stack and `popd` returns to an inherited entry; the stack is state this module cannot
    see. A directory really named `-x` is spelled `./-x`, which resolves normally."""
    tgt = words[1] if len(words) == 2 else None
    if (tgt is None or words[0] == "popd" or tgt.startswith("-") or (words[0] == "pushd" and tgt.startswith("+"))
            or any(c in tgt for c in _NON_LITERAL_PATH_CHARS)):
        return None
    if os.path.isabs(tgt):
        return os.path.normpath(tgt)
    if cur is not None:
        return os.path.normpath(os.path.join(cur, tgt))
    return None


# Stream editors that hand saved bytes on (possibly edited): custody follows them like a reader, but they are not
# in `_READERS` (that is the read-proof allow-list; `sed -i`/`w`/`e` and awk's `system` can write or run).
_BYTE_FILTERS = frozenset({"sed", "awk", "gawk", "mawk", "tac", "nl", "fold", "uniq"})


def _passes_bytes(words: list[str], workspace: str | None) -> bool:
    """Does this command hand its input on as output, so saved bytes stay in custody through it?"""
    return os.path.basename(words[0]) in _BYTE_FILTERS or _segment_reads([os.path.basename(words[0]), *words[1:]], workspace)


def _input_commands(shell: str, *, unwrap: bool = True):
    """Command words, write targets and owned input redirects from the SAME lexer.

    Directory analysis unwraps transparent-looking prefixes. Receipt identity
    requests raw argv instead: wrapper option operands are not proven executables.
    """
    commands = []
    for start, end in _segment_spans(shell):
        source = _join_continuations(shell[start:end])[0]
        spans = _shell_tokens(source)
        if spans is None:
            return None
        tokens = [word for word, _, _ in spans]
        words, word_indices, outputs, inputs, i = [], [], [], [], 0
        while i < len(tokens):
            tok = tokens[i]
            _, begin, token_end = spans[i]
            if tok and set(tok) <= _PUNCT and source[begin:token_end] == tok:
                if tok not in _REDIRECTS or i + 1 == len(tokens):
                    return None
                # A descriptor is an adjacent, wholly unquoted decimal token,
                # not merely an argv value that happens to contain digits.
                fd = None
                if (words and word_indices[-1] == i - 1
                        and re.fullmatch(r"[0-9]+", words[-1])):
                    _, previous, finish = spans[i - 1]
                    if finish == begin and source[previous:finish] == words[-1]:
                        fd = words.pop()
                        word_indices.pop()
                if "<" in tok:
                    inputs.append((fd or '0', tok, tokens[i + 1]))
                if ">" in tok and not (tok == ">&" and tokens[i + 1].isdigit()):
                    outputs.append(tokens[i + 1])
                i += 2
            else:
                words.append(tok)
                word_indices.append(i)
                i += 1
        if unwrap:
            words = _command_words(words)
        targets, _inner = _segment_write_targets(words)
        commands.append((start, end, words, outputs + targets, inputs))
    return commands


class _InputExecution(NamedTuple):
    kind: str
    cwd: str | None
    exact: bool = True
    outputs: tuple[str | None, ...] = ()
    last: int = -1


def _input_sources(words, inputs):
    """One source view for execution AND saved-output custody."""
    return [*words[1:], *(path for _fd, _op, path in inputs)]


def _input_path(path, cwd):
    if any(c in path for c in '$`'):
        return None
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(cwd, path)) if cwd else None


def _route_input(commands, shell, index, workspace, cwd, *, sources=()):
    """Follow the same stdin pipeline for immediate AND saved input."""
    outputs, exact, i = [], True, index
    while True:
        start, end, words, targets, inputs = commands[i]
        outputs.extend(targets)
        if not words:
            return i, outputs, 'unknown', False
        cmd = os.path.basename(words[0])
        if i != index and inputs:
            return i, outputs, 'unknown', False  # a redirected pipeline loses custody
        if cmd in _SHELLS or cmd in ('.', 'source'):
            return i, outputs, 'shell', exact
        if not _passes_bytes(words, workspace):
            return i, outputs, 'unknown', False
        args = words[1:]
        if cmd not in ('cat', 'tee') or (cmd == 'cat' and any(
                a != '-' and _input_path(a, cwd) not in sources for a in args)):
            exact = False
        if any(t in ('>>', '&>>') for t in (_shell_words(shell[start:end]) or [])):
            exact = False
        if (end >= len(shell) or shell[end] != '|' or shell[end:end + 2] == '||'
                or i + 1 >= len(commands)):
            return i, outputs, 'data', exact
        i += 1


def _substitution_execution(child, source, words, targets, cwd, workspace, depth, *, opaque=False):
    """Follow saved bytes through one command substitution of the command whose argv is ``words``.
    Besides what the child itself runs, its OUTPUT is the program text of a command that executes its
    argument (`sh -c "$(cat tmp/script)"`, `eval "$(cat tmp/script)"`): the saved bytes run there. A
    stricter reading than bash (any substitution of such a command, not only the script argument) errs
    toward judging the saved body, never toward admitting it unseen."""
    text = child.text(source)
    execution = _saved_scope_execution(text, targets, cwd, workspace, depth, opaque=opaque)
    if execution and execution.kind != 'data':
        return execution
    if not words or not (os.path.basename(words[0]) == 'eval' or (
            os.path.basename(words[0]) in _SHELLS and _segment_write_targets(words)[1])):
        return execution
    layout = shellinput.layout(text)
    substitutions, undecidable = shellinput.expansions(layout.shell, shell=True)
    commands = None if layout.error or undecidable else _input_commands(
        shellinput.outer_shell(layout.shell, substitutions))
    if commands is None:
        return _InputExecution('unknown', cwd, False)
    for _s, _e, inner, _out, inputs in commands:
        if not inner or not _passes_bytes(inner, workspace):
            continue
        paths = _input_sources(inner, inputs)
        uncertain = any(_input_path(p, cwd) is None for p in paths)
        if uncertain or any(_input_path(p, cwd) in targets for p in paths):
            return _InputExecution('shell', cwd, not uncertain and not opaque)
    return execution


def _saved_scope_execution(script, targets, cwd, workspace, depth, *, opaque=False):
    """Follow saved bytes across a child shell without exporting its cwd."""
    unknown = _InputExecution('unknown', cwd, False)
    if depth > 3:
        return unknown
    layout = shellinput.layout(script)
    substitutions, undecidable = shellinput.expansions(layout.shell, shell=True)
    shell = shellinput.outer_shell(layout.shell, substitutions)
    commands = _input_commands(shell)
    if layout.error or undecidable or commands is None:
        return unknown
    known, forwarded, exact, routed_until = list(targets), [], True, -1
    for i, (start, end, args, _outputs, _inputs) in enumerate(commands):
        if i <= routed_until:
            continue
        # Expansion happens before its enclosing command. Keep output custody
        # for siblings and a consumer in that command, not just later segments.
        for child in substitutions:
            if not start <= child.start <= end:
                continue
            cur = _cwd_before(commands, shell, child.start, cwd)
            execution = _substitution_execution(child, layout.source, args, known, cur,
                                                workspace, depth + 1, opaque=opaque)
            if not execution:
                continue
            if execution.kind != 'data':
                return execution._replace(exact=exact and execution.exact)
            known.extend(p for p in execution.outputs if p is not None)
            forwarded.extend(execution.outputs)
            exact = exact and execution.exact
            opaque = opaque or any(p is None for p in execution.outputs)
        execution = _saved_input_execution(commands, shell, i, known, cwd,
                                           workspace, depth, opaque=opaque)
        if execution:
            if execution.kind != 'data':
                return execution._replace(exact=exact and execution.exact)
            known.extend(p for p in execution.outputs if p is not None)
            forwarded.extend(execution.outputs)
            exact = exact and execution.exact
            opaque = opaque or any(p is None for p in execution.outputs)
            routed_until = execution.last
            continue
        if args and args[:1] != ['cd'] and not command_only_reads(
                shell[start:end], workspace, no_writes=True):
            opaque = True
    if forwarded or opaque:
        return _InputExecution('data', cwd, exact and not opaque,
                               tuple(forwarded) + ((None,) if opaque else ()))
    return None


def _saved_input_kind(words, inputs, targets, cwd, workspace, depth=0, *, opaque=False):
    """Direct execution, retaining stdin sources as well as word operands."""
    if not words:
        return None
    unknown = _InputExecution('unknown', cwd, False)
    if depth > 3:
        return unknown
    cmd = os.path.basename(words[0])
    normalized = set(targets)
    stdin = any(_input_path(p, cwd) in normalized for _fd, _op, p in inputs)
    uncertain = any(_input_path(p, cwd) is None for _fd, _op, p in inputs)
    if opaque and '/' in words[0] and os.path.dirname(words[0]) not in _SYSTEM_PROGRAM_DIRS:
        return unknown
    if _input_path(words[0], cwd) in normalized:
        return _InputExecution('shell', cwd, not opaque)
    if cmd in _SHELLS or cmd in ('.', 'source'):
        _targets, inner = _segment_write_targets(words)
        if inner:
            if stdin or uncertain:
                return unknown  # -c input is not itself the script; custody is opaque
            for script in inner:
                execution = _saved_scope_execution(script, targets, cwd, workspace,
                                                   depth + 1, opaque=opaque)
                if execution:
                    return execution
            return None
        if stdin:
            if any(fd != '0' or op != '<' for fd, op, _p in inputs):
                return unknown
            return _InputExecution('shell', cwd, not opaque)
        if uncertain or (opaque and _operands(words[1:])):
            return unknown
        if (len(words) > 1 and not words[1].startswith('-')
                and _input_path(words[1], cwd) in normalized):
            # After a proven script filename, expanded words are script argv,
            # not a replacement shell program. Its body is still checked.
            return _InputExecution('shell', cwd, not opaque)
        if any(any(c in a for c in '$`') for a in words[1:]):
            return unknown
        if any(_input_path(a, cwd) in normalized for a in _operands(words[1:])):
            return _InputExecution('shell', cwd, not opaque)
        if cwd is None and _operands(words[1:]):
            return unknown
    elif re.fullmatch(r'(?:python[\d.]*|pypy[\d.]*|perl[\d.]*|ruby[\d.]*|node|nodejs|php[\d.]*|lua[\d.]*)', cmd):
        if stdin or uncertain or opaque or any(_input_path(a, cwd) in normalized
                or any(c in a for c in '$`') for a in words[1:]):
            return unknown
    elif stdin or uncertain:
        if not _segment_reads([cmd, *words[1:]], cwd):
            return unknown
    return None


def _saved_input_execution(commands, shell, index, targets, cwd, workspace, depth=0, *, opaque=False):
    start, _end, words, _outputs, inputs = commands[index]
    cur = _cwd_before(commands, shell, start, cwd)
    execution = _saved_input_kind(words, inputs, targets, cur, workspace, depth, opaque=opaque)
    if execution:
        return execution
    if not words:
        return None
    if not _passes_bytes(words, workspace):
        return None
    # A reader can supply the saved bytes by filename OR retained stdin source.
    paths = _input_sources(words, inputs)
    matched = any(_input_path(p, cur) in targets for p in paths)
    uncertain = any(_input_path(p, cur) is None for p in paths)
    if not matched and not uncertain:
        return None
    last, writes, kind, exact = _route_input(commands, shell, index, workspace, cur, sources=targets)
    if kind == 'data' and not writes:
        return None
    # A reader's saved output still owns these bytes even when no executable
    # immediately follows. Resolve each writer at its own cwd, not the later
    # consumer's, and carry opacity rather than silently discarding the edge.
    outputs = tuple(_input_path(path, _cwd_before(commands, shell, start, cwd))
                    for start, _end, _words, written, _inputs in commands[index:last + 1]
                    for path in written)
    consumer_cwd = _cwd_before(commands, shell, commands[last][0], cwd)
    return _InputExecution(kind, consumer_cwd, exact and matched and not uncertain and not opaque,
                           outputs, last)


def _cwd_before(commands, shell, pos, cwd):
    cur = cwd
    for start, end, words, _, _inputs in commands:
        if start <= pos <= end:
            break
        if words[:1] == ['cd']:
            cur = _follow_cd(words, cur)
        if shell[end:end + 1] in ('(', ')'):
            cur = None
    return cur


def _input_refusal(layout, shell, substitutions, level, workspace, roots, cwd, depth):
    commands = _input_commands(shell)
    if commands is None:
        return prompts.load('external_write_unproven')
    for doc in layout.documents:
        owner = next((i for i, (s, e, _, _, _) in enumerate(commands) if s <= doc.operator <= e), None)
        if owner is None:
            return prompts.load('external_write_unproven')
        cur = _cwd_before(commands, shell, doc.operator, cwd)
        body = doc.text(layout.source)
        if not doc.quoted:
            scripts, unknown = shellinput.expansions(body)
            if unknown:
                return prompts.load('external_write_unproven')
            for substitution in scripts:
                refusal = command_refusal(substitution.text(body), level, workspace, roots,
                                          _cwd=cur, _depth=depth + 1)
                if refusal:
                    return refusal
        i, targets, kind, exact = _route_input(commands, shell, owner, workspace, cur)
        if kind == 'data' and targets:
            if cur is None or any(any(c in target for c in '$`') for target in targets):
                return prompts.load('external_write_unproven')
            targets = [os.path.normpath(os.path.join(cur, target)) for target in targets]
            unknown_origin, routed_until = False, i
            for later, (start, end, words, outputs, _inputs) in enumerate(commands[i + 1:], i + 1):
                if later <= routed_until:
                    continue
                later_cwd = _cwd_before(commands, shell, start, cwd)
                for child in substitutions:
                    if not start <= child.start <= end:
                        continue
                    execution = _substitution_execution(child, layout.source, words, targets,
                                                        later_cwd, workspace, depth + 1,
                                                        opaque=unknown_origin)
                    if execution:
                        exact = exact and execution.exact
                        if execution.kind != 'data':
                            kind, cur = execution.kind, execution.cwd
                            break
                        targets.extend(p for p in execution.outputs if p is not None)
                        unknown_origin = unknown_origin or any(p is None for p in execution.outputs)
                if kind != 'data':
                    break
                if not words:
                    continue
                execution = _saved_input_execution(commands, shell, later, targets, cwd,
                                                    workspace, depth, opaque=unknown_origin)
                if execution:
                    exact = exact and execution.exact
                    if execution.kind == 'data':
                        targets.extend(p for p in execution.outputs if p is not None)
                        unknown_origin = unknown_origin or any(p is None for p in execution.outputs)
                        routed_until = execution.last
                        continue
                    kind, cur = execution.kind, execution.cwd
                    break
                # A subsequent modification/copy or opaque nested command
                # invalidates byte custody; do not analyze the old body as the
                # consumer's current script. This is not general program taint.
                _, inner = _segment_write_targets(words)
                sources = _input_sources(words, _inputs)
                mentions_input = any(_input_path(path, later_cwd) in targets for path in sources)
                if outputs and (mentions_input or any(_input_path(path, later_cwd) is None for path in sources)):
                    exact = False
                    if later_cwd is None or any('$' in p or '`' in p for p in outputs):
                        unknown_origin = True
                    else:
                        targets.extend(os.path.normpath(os.path.join(later_cwd, p)) for p in outputs)
                if any(not command_only_reads(s, workspace, no_writes=True) for s in inner):
                    exact, unknown_origin = False, True
        if kind == 'unknown' or (kind == 'shell' and not exact):
            return prompts.load('external_write_unproven')
        if kind == 'shell':
            body_commands = _input_commands(shellinput.layout(body).shell)
            if body_commands is None:
                return prompts.load('external_write_unproven')
            for _, _, words, _, _inputs in body_commands:
                if not words:
                    continue
                cmd = os.path.basename(words[0])
                writes, inner = _segment_write_targets(words)
                if (any(c in cmd for c in '$`') or (not writes and not inner and cmd not in _SHELLS
                        and not _segment_reads([cmd, *words[1:]], workspace))):
                    return prompts.load('external_write_unproven')
            refusal = command_refusal(body, level, workspace, roots, _cwd=cur, _depth=depth + 1)
            if refusal:
                return refusal
    return None


def _operands(args: list[str]) -> list[str]:
    out, rest = [], False
    for a in args:
        if rest or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            rest = True
    return out


def _segment_write_targets(words: list[str]) -> tuple[list[str], list[str]]:
    """(paths this one simple command WRITES or deletes, nested shell scripts it runs)."""
    words = _command_words(words)
    if not words:
        return [], []
    cmd, args = os.path.basename(words[0]), words[1:]
    if cmd in _SHELLS:
        for i, a in enumerate(args):
            if a.startswith("-") and not a.startswith("--") and "c" in a and i + 1 < len(args):
                return [], [args[i + 1]]
        return [], []
    ops = _operands(args)
    targets: list[str] = []
    if cmd in ("cp", "mv", "install", "ln"):  # -t DIR names the destination directly
        for i, a in enumerate(args):
            if a in ("-t", "--target-directory") and i + 1 < len(args):
                targets.append(args[i + 1])
                ops = [o for o in ops if o != args[i + 1]]
            elif a.startswith("--target-directory="):
                targets.append(a.split("=", 1)[1])
    if cmd in _DEST_LAST:
        targets += ops[-1:] if ops and not targets else []
        if cmd == "mv":
            targets += ops
    elif cmd in _ALL_OPERANDS:
        targets += ops
    elif cmd in _SKIP_FIRST:
        targets += ops[1:]
    elif cmd == "sed":
        shorts = _short_flags(args)
        if "i" in shorts or any(a.startswith("--in-place") for a in args):
            scripted = "e" in shorts or "f" in shorts or any(a.startswith(("--expression", "--file")) for a in args)
            targets += ops if scripted else ops[1:]
    elif cmd == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif cmd == "truncate":
        targets += ops
    elif cmd in ("curl", "wget"):
        for i, a in enumerate(args):
            if (a in ("-o", "--output") or (cmd == "wget" and a in ("-O", "-P"))) and i + 1 < len(args):
                targets.append(args[i + 1])
    return targets, []


def _escaping_write_target(command: str, workspace: str | None, _cwd="", _depth=0, *,
                           level="none", roots=()) -> str | _UnprovenWrite | _InputRefusal | None:
    """The first path a write/delete in ``command`` would touch OUTSIDE the workspace, resolved
    lexically (normpath, like :func:`is_external`) against the workspace — or None.

    The path scan in :func:`command_refusal` judges ROOTED tokens; a relative `../root/out` is
    not rooted, and a path inside a `bash -c "…"` string is read as a quoted pattern, so both walked
    through. Only write TARGETS are judged — redirects, tee/cp/mv/rm/ln/install/touch/mkdir/sed -i
    operands and the like. Relative READS (`cat ../x`) are deliberately unchanged. A target built
    from an unresolved expansion or reached after an unknown cwd is UNPROVEN, never permission
    to proceed. Heredoc ownership is shared with the rooted scan; no header tail is discarded."""
    if not workspace:
        return None
    if _depth > 3:
        return _UNPROVEN_WRITE
    cwd = os.path.normpath(os.path.expanduser(workspace)) if _cwd == "" else _cwd
    layout = shellinput.layout(command)
    if layout.error:
        return _UNPROVEN_WRITE
    command = layout.shell
    tokens = _shell_tokens(command)
    if tokens is None:
        return _UNPROVEN_WRITE
    words = [w for w, _, _ in tokens]
    joined = _join_continuations(command)[0]
    operator = [_is_operator(w, joined, s, e) for w, s, e in tokens]
    cur: str | None = cwd
    seg: list[str] = []

    def judge(tok: str) -> str | _UnprovenWrite | None:
        if not tok or tok == "-":
            return _UNPROVEN_WRITE
        if any(c in tok for c in "$`") or re.match(r"^~[^/]", tok):
            return _UNPROVEN_WRITE
        p = os.path.expanduser(tok)
        rooted = os.path.isabs(p)
        if not rooted:
            if cur is None:
                return _UNPROVEN_WRITE
            p = os.path.join(cur, p)
        # A top-level ABSOLUTE target is the path scan's to judge (its dependency-cache and
        # declared-root policy lives there); only a relative one, or one inside a nested shell
        # string the scan reads as a quoted pattern, is judged here.
        if rooted and _depth == 0:
            return None
        full = os.path.normpath(p)
        return full if is_external(full, workspace) and not _exempt(full) else None

    def flush() -> str | _UnprovenWrite | _InputRefusal | None:
        nonlocal cur, seg
        words_, seg = _command_words(seg), []
        if not words_:
            return None
        if words_[0] == "cd":
            cur = _follow_cd(words_, cur)
            return None
        targets, inner = _segment_write_targets(words_)
        for t in targets:
            hit = judge(t)
            if hit:
                return hit
        for script in inner:
            # Nested execution returns to the SAME boundary owner. Calling only
            # the target scan here would mask a nested heredoc without judging
            # its input execution/expansions.
            refusal = command_refusal(script, level, workspace, roots,
                                      _cwd=cur, _depth=_depth + 1)
            if refusal:
                return _InputRefusal(refusal)
        return None

    i = 0
    while i < len(words):
        w = words[i]
        if operator[i]:
            if ">" in w and "<" not in w:
                nxt = words[i + 1] if i + 1 < len(words) else None
                if nxt is not None and not operator[i + 1] and not (
                        "&" in w and w.endswith("&") and nxt.lstrip("&").isdigit()):
                    hit = judge(nxt)
                    if hit:
                        return hit
                    i += 1
                if seg and seg[-1].isdigit():
                    seg.pop()
            if any(c in w for c in ";&|\n()") and not w.endswith(">&"):
                hit = flush()
                if hit:
                    return hit
                if '(' in w or ')' in w:
                    cur = None  # grouped/substitution cwd must not leak into its parent
        else:
            seg.append(w)
        i += 1
    return flush()


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
    "/.gem/ruby/",            # Ruby gems: ~/.gem/ruby/ (not ~/.gem/credentials)
    "/gem/ruby/",             # Ruby gems: ~/.local/share/gem/ruby/
    "/ruby/gems/",            # Ruby gems: /usr/lib/ruby/gems/, rbenv/rvm, bundler .../ruby/gems/
    "/node_modules/",         # Node packages: any node_modules holds public JS source, never secrets
)


# The roots the HARNESS itself declares writable ("The writable roots are `a`, `b`." in Codex's
# permissions text). The harness has already decided those directories are the run's own — cwd plus
# the install/scratch dir its build tools are configured to use (JAVA_TOOL_OPTIONS
# -Dmaven.repo.local, GOMODCACHE, CARGO_HOME ...). Walked: feed-pipeline-java x ornith1.5_9b
# 1791513868 ran a read-only `find <install>/m2/repository -iname '*opencsv*'` to learn which jar
# the build resolved and was refused "outside the working directory" on every try (the hard-coded
# dependency-cache markers know `~/.m2/repository`, not a cache the build is told to keep elsewhere);
# it never read the real OpenCSV API and wrote classes that do not exist. Derived from the request,
# never a hard-coded path.
_WRITABLE_ROOTS_SENTENCE = re.compile(r"writable[ _]roots?\b[^`\n]{0,40}?((?:\s*`[^`\n]+`[\s,.]*(?:and\s+)?)+)",
                                      re.IGNORECASE)
_BACKTICKED = re.compile(r"`([^`\n]+)`")


def declared_roots(messages) -> tuple[str, ...]:
    """Absolute directories the harness declares writable in its system/developer permission text,
    else (). The sentence is the harness's own; cria only reads it back."""
    roots: list[str] = []
    for m in messages or []:
        if not isinstance(m, dict) or m.get("role") not in ("system", "developer"):
            continue
        c = m.get("content")
        text = c if isinstance(c, str) else " ".join(
            str(part.get("text", "")) for part in (c or []) if isinstance(part, dict))
        for sent in _WRITABLE_ROOTS_SENTENCE.finditer(text):
            for r in _BACKTICKED.findall(sent.group(1)):
                r = r.strip()
                r = os.path.normpath(r)
                home = os.path.normpath(os.path.expanduser("~"))
                # $HOME and every ancestor of it would expose the whole account: not a run root.
                if (os.path.isabs(r) and r != os.sep and r not in roots
                        and not (home == r or home.startswith(r + os.sep))):
                    roots.append(r)
    return tuple(roots)


# The build's OWN dependency location, when a TOOL result printed it (a JVM option the launcher echoes).
# Only a location that, with symlinks resolved on BOTH sides, stays inside a declared root counts: that
# is the one case where cria knows the read is allowed. Assistant text is the model's guess and never
# a source.
_BUILD_REPO_FLAG = re.compile(r"-Dmaven\.repo\.local=([^\s\"',;]+)")


def _text_of(m) -> str:
    c = m.get("content") if isinstance(m, dict) else None
    return c if isinstance(c, str) else " ".join(
        str(part.get("text", "")) for part in (c or []) if isinstance(part, dict))


def _really_inside(path: str, roots) -> bool:
    """``path`` lies in one of ``roots`` after resolving symlinks on both sides."""
    rp = os.path.realpath(path)
    return any(rp == rr or rp.startswith(rr + os.sep) for rr in (os.path.realpath(r) for r in roots))


def _run_roots(messages, workspace: str | None) -> tuple[str, ...]:
    """Declared roots other than the project itself (the workspace is the model's own writing: never a
    dependency's real surface, and it is always readable anyway)."""
    ws = os.path.normpath(workspace) if workspace else ""
    return tuple(r for r in declared_roots(messages)
                 if not (ws and (ws == r or ws.startswith(r + os.sep))))


def build_dependency_locations(messages, roots) -> tuple[str, ...]:
    """Locations a TOOL result shows the build was told to keep dependencies in, accepted only when
    they really (symlinks resolved) stay inside ``roots``. The single source for both what the model
    is told and where cria searches."""
    deps: list[str] = []
    if not roots:
        return ()
    for m in messages or []:
        # Only TOOL results: the launcher's own echo is a fact; assistant text is a guess.
        if isinstance(m, dict) and m.get("role") == "tool":
            for loc in _BUILD_REPO_FLAG.findall(_text_of(m)):
                loc = os.path.normpath(os.path.expanduser(loc))
                if os.path.isabs(loc) and loc not in deps and _really_inside(loc, roots):
                    deps.append(loc)
    return tuple(deps)


def dependency_roots(messages, workspace: str | None = None) -> tuple[str, ...]:
    """The directories cria searches for this run's dependencies, and exactly the ones
    `readable_roots_note` tells the model about: the exact build locations first, then the declared
    non-workspace roots. () when the harness declared nothing beyond the project."""
    roots = _run_roots(messages, workspace)
    if not roots:
        return ()
    deps = build_dependency_locations(messages, roots)
    return (*deps, *(r for r in roots if r not in deps))


def readable_roots_note(messages, workspace: str | None, *, include_build: bool = True) -> str:
    """Restate harness-declared writable roots without downgrading them to read-only.

    API inspection uses read-only commands, but this note neither grants extra
    access nor overrides the caller's permission policy. Empty without trusted roots.
    """
    roots = _run_roots(messages, workspace)
    if not roots:
        return ""
    deps = build_dependency_locations(messages, roots) if include_build else ()
    build = (prompts.fill(prompts.load("readable_roots_build"), deps=", ".join(deps)) if deps else "")
    return prompts.fill(prompts.load("readable_roots"), roots=", ".join(roots), build=build)


def annotate_build_locations(messages, workspace: str | None) -> list[dict]:
    """Place each observed location after its first source result, never in the system.

    Rebuilding an appended history recreates exactly the same earlier annotations.
    The authoritative tool text and native call coordinates remain untouched.
    """
    roots = _run_roots(messages, workspace)
    seen: set[str] = set()
    out = []
    for message in messages:
        out.append(message)
        locations = [p for p in build_dependency_locations([message], roots) if p not in seen]
        if locations:
            out.append({'role': 'user', bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.DEPENDENCY,
                        'content': prompts.render('dependency_build_locations',
                                                  locations=", ".join(locations)).strip()})
            seen.update(locations)
    return out


def _in_declared_root(path: str, roots) -> bool:
    if not roots or not path or not path.strip():
        return False
    p = os.path.normpath(os.path.expanduser(path.strip()))
    return os.path.isabs(p) and any(p == r or p.startswith(r + os.sep) for r in roots)


# --- Proving a command READS ---------------------------------------------------------------
# `shelltool.writes_something` is deliberately GENEROUS toward "this might have written" — right for
# its callers, wrong as proof of safety: `find … | xargs rm`, `1>file`, `curl -o`, `tar -C` all read
# as read-only to it. Letting a command touch a harness-declared root needs the opposite stance, a
# POSITIVE allow-list: every pipeline segment must be a known reader, and anything else — xargs,
# a shell or interpreter, an unknown program, a substitution — is NOT proven and is refused.
_PUNCT = set(";&|()<>\n")
_READERS = {"cd", "echo", "printf", "pwd", "true", "ls", "cat", "head", "tail", "wc", "grep", "egrep",
            "fgrep", "rg", "stat", "file", "du", "find", "sort", "unzip", "jar", "javap", "readlink",
            "realpath", "basename", "dirname", "cut", "tr"}
_FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


_SEPARATORS = {";", "&&", "||", "|", "&", "\n"}
_REDIRECTS = {">", ">>", "<", ">&", "<&", "&>", "&>>", ">|"}


def _short_flags(args) -> str:
    return "".join(a.lstrip("-") for a in args if a.startswith("-") and not a.startswith("--"))


# `sed -n '100,180p' FILE`: the idiomatic way to read a line range. With `-n` and ONE script that is nothing but a line
# address and `p`, sed can only print — no `w`, `e`, `r`, `-i`, `-f`, `;` chains or long options (walked on cart-billing-go
# x ornith1.5_9b: `sed -n '100,180p' <modcache>/encoding.go` and `cat -n f | sed -n '100,180p'` were refused as "sed is not a
# read-only inspector", three calls in a row, which fired the refusals steer).
_SED_PRINT_RANGE = re.compile(r"\d+(,(\d+|\$))?p|\$p")


def _sed_prints_only(args: list[str]) -> bool:
    return (len(args) >= 2 and args[0] == "-n" and _SED_PRINT_RANGE.fullmatch(args[1]) is not None
            and not any(a.startswith("-") and a != "-" for a in args[2:]))


def _without_timeout(words: list[str]) -> list[str]:
    """``timeout [-s SIG] [-k D] DURATION cmd ...`` runs ``cmd`` under a clock and does nothing else, so the read proof judges ``cmd``
    (the grammar is the ``timeout`` row of `_KILL_WRAPPERS`). Refusing it as "timeout is not one of the read-only inspectors" was a
    false statement about ``timeout 15 grep -n X <declared path>`` (Go cell g1); only this wrapper is transparent to the proof (sudo, env and
    xargs change who or what runs, `time -o` writes a file). A bare ``timeout`` with nothing after the duration stays unproven."""
    if not words or _program_name(words[0]) != "timeout":
        return words
    takes, positional = _KILL_WRAPPERS["timeout"]
    rest = words[1:]
    while rest and rest[0].startswith("-") and rest[0] != "-":
        flag = rest[0]
        rest = rest[(2 if flag in takes else 1):]
        if flag == "--":
            break
    rest = rest[positional:]
    return rest or words


def _segment_failure(words: list[str], workspace: str | None = None, no_writes: bool = False):
    """``None`` when this one segment is a proven reader, else ``(reason, index)``: why it is not and which
    word of the segment carries the reason (0 = the command word). The ONE place those decisions are made;
    ``_segment_reads`` is its boolean."""
    words = _without_timeout(words)
    cmd, args = words[0], words[1:]
    if no_writes and cmd == "tee":
        return "tee_writes", 0
    if cmd == "cd":  # moves the REAL cwd, which relative redirect targets resolve against
        if len(args) != 1:
            return "cd_target", 0
        return None if _plain_project_path(args[0], workspace) else ("cd_target", 1)
    if cmd == "tee":  # a copy of stdin: harmless exactly when every file it writes is in the project
        for k, a in enumerate(args, 1):
            if a.startswith("-") or not _plain_project_path(a, workspace, allow_devnull=True):
                return "tee_target", k
        return None
    if cmd == "sed" and _sed_prints_only(args):
        return None
    if cmd not in _READERS:
        return "not_a_reader", 0
    if cmd == "find":
        for k, a in enumerate(args, 1):
            if a in _FIND_ACTIONS:
                return "reader_option", k
        return None
    # GNU getopt accepts ANY unambiguous prefix of a long option (`sort --outp=f` is --output,
    # `--comp=prog` runs a program), so a denylist of spellings is unsound: sort and file take no
    # long option at all.
    if cmd in ("sort", "file"):
        for k, a in enumerate(args, 1):
            if a.startswith("--"):
                return "reader_option", k
        forbidden = set("oTCm" if cmd == "file" else "oT")
        if set(_short_flags(args)) & forbidden:
            for k, a in enumerate(args, 1):
                if a.startswith("-") and set(a.lstrip("-")) & forbidden:
                    return "reader_option", k
            return "reader_option", 0
        return None
    if cmd == "rg":  # --pre / --hostname-bin run programs; refuse them and every prefix of them
        for k, a in enumerate(args, 1):
            if a.startswith("--") and a != "--":
                o = a.split("=", 1)[0]
                if (o.startswith(("--pre", "--hostname-bin")) or "--pre".startswith(o)
                        or "--hostname-bin".startswith(o)):
                    return "reader_option", k
        return None
    if cmd == "unzip":  # a LISTING flag is mandatory: bare `unzip x.zip` extracts
        flags = set(_short_flags(args))
        if (bool(flags & set("lpvtZ")) and flags <= set("lpvqtZ1")
                and not any(a.startswith("--") for a in args)):
            return None
        return "reader_option", next((k for k, a in enumerate(args, 1) if a.startswith("--")), 0)
    if cmd in ("jar", "javap"):
        for k, a in enumerate(args, 1):
            if a.startswith(("-J", "@")):
                return "reader_option", k  # -J hands the JVM an option (-Xlog:…:file=F writes); @file can hide one
    if cmd == "jar":  # `jar tf x.jar`: the table of contents, never create/extract/update
        first = args[0].lstrip("-") if args else ""
        return None if (bool(first) and "t" in first and set(first) <= set("tvf")) else ("reader_option", 1 if args else 0)
    return None


def _segment_reads(words: list[str], workspace: str | None = None, no_writes: bool = False) -> bool:
    return _segment_failure(words, workspace, no_writes) is None


# A path word containing any of these is not ONE literal path: the shell may expand it (variable,
# substitution, glob, brace, tilde). Shared by every "is this a literal path" question here.
_NON_LITERAL_PATH_CHARS = "${}*?[~`"


def _plain_project_path(path: str, workspace: str | None, allow_devnull: bool = False) -> bool:
    """A literal path inside the project: no expansion (`$`, braces, globs, `~`) can make it name
    anything else, and it is not outside the workspace."""
    if not path or any(c in path for c in _NON_LITERAL_PATH_CHARS) or path == "-":
        return False
    return (allow_devnull and _exempt(path)) or not is_external(path, workspace)


def _redirect_ok(op: str, target: str | None, workspace: str | None, no_writes: bool = False) -> bool:
    """A redirect is harmless when it writes nothing outside the project: an fd duplication
    (`2>&1`), /dev/null, or a file inside the workspace. `&>`, `>|`, `1>` all reduce to this."""
    if ">" not in op:
        return True  # `<` input: reading, judged by the path scan like any other operand
    if no_writes:  # nothing may be written ANYWHERE: only an fd duplication or /dev/null
        if op == ">&" and target is not None and (target.isdigit() or target == "-"):
            return True
        return target is not None and _exempt(target) and "<" not in op and "(" not in op
    if "&" in op and op.rstrip("&|").endswith(">&") and target is not None and target.lstrip("&").isdigit():
        return True
    if target is None or "<" in op or "(" in op:
        return False
    return _plain_project_path(target, workspace, allow_devnull=True)


class _ProofFailure(NamedTuple):
    """The first part of a command the read-only proof could not verify. ``start``/``end`` are offsets in
    the text the proof was given — for ``command_refusal`` a same-length projection of the coder's command,
    so they are offsets of the ORIGINAL text too; continuations are mapped back through the join owner."""
    reason: str
    start: int
    end: int
    word: str = ""


_ASSIGNMENT_AT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")


def _read_proof(command: str, workspace: str | None, *, no_writes: bool = False) -> _ProofFailure | None:
    """``None`` when EVERY segment of ``command`` is a known reader and every redirect stays inside the
    project (or /dev/null); else the SELECTED unverified part, with its exact source span and reason.
    Unknown ⇒ a failure. Selection order: the raw text markers (`<<`, a backtick, `$(`) are checked
    before the command is split — they reject quoted text too — then tokenizing, then segment by segment
    in source order. So the selected part is the first one in THAT order, not necessarily the earliest
    offset in the source: a marker late in the command is selected over an earlier unverified segment. ``no_writes`` is the stricter proof that the command changes NO file anywhere:
    output redirects other than fd duplication and /dev/null, and ``tee``, are refused too (a write into
    the project is harmless to the O1 guard, not to a caller asking whether a file it read is still
    current). ``command_only_reads`` is this function's boolean: the decisions are one set."""
    if not command:
        return _ProofFailure("empty", 0, 0)
    marks = [(command.find(m), m, r) for m, r in (("<<", "heredoc"), ("`", "substitution"), ("$(", "substitution"))
             if m in command]
    if marks:
        at, marker, reason = min(marks)
        return _ProofFailure(reason, at, at + len(marker))
    # Read each ANSI-C string (`$'\''`) to the quote bash ends it at: a same-length projection, so
    # every span below is still an offset of the text this proof was given.
    lay = shellinput.layout(command)
    if lay.error:
        return _ProofFailure("unparsed", 0, len(command))
    command = lay.literal_shell
    tokens = _shell_tokens(command)
    if tokens is None:
        return _ProofFailure("unparsed", 0, len(command))
    joined, origin = _join_continuations(command)

    def span(first: int, last: int) -> tuple[int, int]:      # token indices -> offsets in ``command``
        return origin[tokens[first][1]], origin[tokens[last][2] - 1] + 1

    words = [w for w, _, _ in tokens]
    operator = [_is_operator(w, joined, s, e) for w, s, e in tokens] + [True]   # + the closing ";"
    seg: list[str] = []
    seg_tok: list[int] = []
    i = 0
    while i <= len(words):
        w = words[i] if i < len(words) else ";"
        if operator[i]:
            # shlex glues adjacent operator characters into ONE token (`;>`, `|<`, `&&>`, `\n>`), which
            # would hide a separator inside what looks like a redirect. Only a token that is exactly
            # one known operator is understood; any other combination is unproven.
            if w not in _SEPARATORS and w not in _REDIRECTS and set(w) != {"\n"}:
                return _ProofFailure("operator", *span(i, i), w)
            if w in _REDIRECTS:
                if seg and seg[-1].isdigit():
                    seg.pop()  # the fd number of `2>file`
                    seg_tok.pop()
                nxt = words[i + 1] if i + 1 < len(words) else None
                if nxt is not None and operator[i + 1]:
                    nxt = None
                if not _redirect_ok(w, nxt, workspace, no_writes):
                    return _ProofFailure("redirect_strict" if no_writes else "redirect",
                                         *span(i, i + 1 if nxt is not None else i), w)
                i += 2 if nxt is not None else 1
                continue
            if seg:
                failed = _segment_failure(seg, workspace, no_writes)
                if failed:
                    reason, k = failed
                    lo, hi = span(seg_tok[0], seg_tok[-1])
                    if reason == "not_a_reader" and _ASSIGNMENT_AT.match(joined[tokens[seg_tok[0]][1]:tokens[seg_tok[0]][2]]):
                        reason = "assignment"             # an UNQUOTED `name=` in the source: quotes are not one
                    return _ProofFailure(reason, lo, hi, seg[0])
            seg = []
            seg_tok = []
        else:
            seg.append(w)
            seg_tok.append(i)
        i += 1
    return None


def command_only_reads(command: str, workspace: str | None, *, no_writes: bool = False) -> bool:
    """True only when EVERY segment of ``command`` is a known reader and every redirect stays inside
    the project (or /dev/null) — ``_read_proof`` found nothing it could not verify."""
    return _read_proof(command, workspace, no_writes=no_writes) is None


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


def _refusal(verb: str, path: str, workspace: str | None = None, roots=(), level: str = "none") -> str:
    # prompts/external_path_refusal.txt — {{PATH}} takes the quoted repr, matching the old f"{path!r}".
    # {{ROOT}} names the ACTUAL project directory when known: the anonymous "the project directory"
    # left a blocked model inventing roots (/tmp/src, /tmp/project) for whole runs — the refusal is
    # the one place cria can state the real one.
    root = f" ({workspace})" if workspace else ""
    if _case_typo_of_workspace(path, workspace):
        note = prompts.load("external_path_case_note")
    elif _in_declared_root(path, roots):
        # A WRITE into a harness-declared root: reads of it are allowed, so say what the rule is.
        note = prompts.load("external_path_declared_root_note")
    else:
        # A refused package-manager cache root (~/.m2, ~/.gradle, ...) draws the offline-misdiagnosis
        # note: the artifact subtree IS readable and this is not a network limit.
        subtree = _dep_cache_root_hint(path)
        note = (prompts.fill(prompts.load("external_path_depcache_note"), subtree=subtree)
                if subtree else "")
    return prompts.fill(prompts.load("external_path_refusal"), verb=verb, path=repr(path), root=root,
                        casenote=note,
                        scratch=(probediscovery.scratch_clause(Path(workspace)) if workspace
                                 else prompts.load_map("external_path_scratch")["default"]),
                        reads=("" if level == "read" else prompts.fill(
                            prompts.load("external_path_reads_allowed"),
                            caches=", ".join(sub for _m, sub in _DEP_CACHE_ROOTS))))


def path_refusal(path: str, is_write: bool, level: str, workspace: str | None, roots=()) -> str | None:
    """The refusal for a synthetic file tool's EXPLICIT path, or None when allowed. read_file/list_dir
    are reads; write_file/edit_file are writes."""
    if level == "write" or _exempt(path) or not is_external(path, workspace):
        return None
    # A READ of a dependency-artifact cache is grounding, not exfiltration — allowed at every level.
    # A WRITE into it is refused unless the operator chose `write` (falls through below).
    if not is_write and (_is_dependency_cache(path) or _in_declared_root(path, roots)):
        return None
    if level == "read" and not is_write:
        return None
    return _refusal("Writing" if is_write else "Reading", path, workspace, roots, level)


def _root_glob_may_recurse(source: str) -> bool:
    """Can this active filename pattern supply a recursive rm option? No IO."""
    def glob_fields(source):
        # Quote removal must not turn quoted wildcard data into active syntax.
        unquoted = {i: c for i, c in _unquoted_chars(source)}
        if not any(c in '*?[' for c in unquoted.values()):
            return []
        placeholder = '\U000f0000'
        while placeholder in source:
            placeholder = chr(ord(placeholder) + 1)
        projected, patterns, i = [], [], 0
        while i < len(source):
            c = unquoted.get(i)
            if c in ('*', '?'):
                patterns.append(c)
                projected.append(placeholder)
                i += 1
            elif c == '[':
                start = i + 1
                if source[start:start + 1] in ('!', '^'):
                    start += 1
                if source[start:start + 1] == ']':
                    start += 1
                end = source.find(']', start)
                if (end < 0 or unquoted.get(end) != ']'
                        or any(ch in "[]\\\"'" for ch in source[i + 1:end])):
                    return None  # unsupported class: retain possibility
                pattern = source[i:end + 1]
                if pattern.startswith('[^'):
                    pattern = '[!' + pattern[2:]
                patterns.append(pattern)
                projected.append(placeholder)
                i = end + 1
            else:
                projected.append(source[i])
                i += 1
        tokens = _shell_tokens(''.join(projected), extra_wordchars=placeholder)
        if tokens is None or len(tokens) != 1:
            return None
        shape = tokens[0][0]
        active = iter(patterns)
        fields = [[]]
        for char in shape:
            if char == placeholder:
                fields[-1].append(next(active))
            else:
                # fnmatch's literal spellings preserve quoted metacharacters.
                fields[-1].append({'*': '[*]', '?': '[?]', '[': '[[]'}.get(char, char))
        return fields

    def glob_may_recurse(source):
        first = next(i for i, c in _unquoted_chars(source) if c in '*?[')
        prefix = _shell_tokens(source[:first])
        if prefix and prefix[0][0] and not prefix[0][0].startswith('-'):
            return False
        fields = glob_fields(source)
        if fields is None:
            return True
        for field in fields:
            pattern = ''.join(field)
            if any(fnmatchcase('--recursive'[:n], pattern) for n in range(3, len('--recursive') + 1)):
                return True
            # Intersect the glob with short options containing r/R. Four
            # states: start, initial dash, non-dash option, recursive option.
            # This avoids enumerating flag combinations or treating [ab] as r.
            def advance(states, atom):
                result = set()
                for state in states:
                    if state == 0 and fnmatchcase('-', atom):
                        result.add(1)
                    elif state:
                        if any(fnmatchcase(c, atom) for c in ('r', 'R')):
                            result.add(3)
                        if state >= 2:
                            result.add(state)
                        elif atom not in ('-', '[-]'):
                            result.add(2)
                return result
            states = {0}
            for atom in field:
                if atom == '*':
                    while True:
                        expanded = states | advance(states, '?')
                        if expanded == states:
                            break
                        states = expanded
                else:
                    states = advance(states, atom)
            if 3 in states:
                return True
        return False

    return glob_may_recurse(source)


_ROOT_WORD = re.compile(r"(?:/+(?:\.\.?(?=/|$))?)+\*?")


def _is_root_word(word: str) -> bool:
    """`/`, `/*` and every spelling of the same directory: `//`, `///`, `/.`, `/./`, `/..`, `//*`."""
    return bool(_ROOT_WORD.fullmatch(word))


_ASSIGN_WORD = re.compile(r"([A-Za-z_]\w*)=")
_ASSIGN_KEYWORDS = frozenset({"export", "declare", "local", "readonly", "typeset"})


class _RootFact(NamedTuple):
    """HOW an operand was found to be the root (or the home directory): `kind` is `shape` (a spelling of
    `/`), `dotdot` (a path whose `..` leads back to `/`), `variable` (`$R` with `R=/` assigned earlier in the
    same script) or `home` (a variable that is the home directory). Carried so the refusal can say the real
    fact instead of a generic claim."""
    kind: str
    operand: str
    name: str = ""
    value: str = ""


def _dotdot_root(text: str) -> bool:
    """Is this literal path a directory that resolves to `/` through `.`/`..` steps? Resolved on THIS host's
    filesystem (`realpath`), so a symlink in front of a `..` is followed the way the kernel follows it: with
    `/tmp/link` pointing at `/usr`, `/tmp/link/..` IS `/`, and a lexical collapse would call it `/tmp`.
    Only a path that ENDS in a directory step is asked (`rm /link` unlinks the link; it never reaches what the
    link points at). Unseen: a link on another host than the one cria runs on."""
    base = text[:-1] if text.endswith("/*") else text
    if not base.startswith("/") or re.search(r"[$*?\[`{]", base) or not re.search(r"(?:^|/)\.\.?/*$", base):
        return False
    return os.path.realpath(base) == "/"


def _typed_operand(word: str, source: str, env: dict[str, str]) -> tuple[str, tuple[str, ...]] | None:
    """The operand's text with every `$NAME` / `${NAME}` replaced by a value assigned earlier in the same
    script, and the names used; None when any part is not a typed fact (a variable never assigned here, a
    value from the environment, single-quoted or backslashed text, a substitution). `$HOME` and `~` are the
    home directory. Operand text without a `$` is its own answer."""
    if "$" not in source:
        return word, ()
    if "'" in source or "\\" in source:
        return None
    names: list[str] = []

    def value(match):
        name = match.group(1) or match.group(2)
        known = env.get(name, "~" if name == "HOME" else None)
        if known is None:
            raise KeyError(name)
        names.append(name)
        return known
    try:
        text = re.sub(r"\$(?:(\w+)|\{(\w+)\})", value, source.replace('"', ""))
    except KeyError:
        return None
    return (None, ()) if "$" in text or "`" in text else (text, tuple(names))


def _root_fact(word: str, source: str, env: dict[str, str]) -> _RootFact | None:
    typed = _typed_operand(word, source, env)
    if typed is None or typed[0] is None:
        return None
    text, names = typed
    if _is_root_word(text) or _dotdot_root(text):
        if names:
            return _RootFact("variable", source, names[-1], env.get(names[-1], "~"))
        return _RootFact("shape" if _is_root_word(text) else "dotdot", source)
    if names and text.rstrip("/") == "~":
        return _RootFact("home", source, names[-1] if names[-1] in env else "", "~")
    return None


def _note_assignment(segment, env: dict[str, str]) -> None:
    """A segment of nothing but assignments (`R=/`, `export R=/`, `local -r R=/`) sets shell variables for
    the rest of the script; `R=/ rm …` does not (the shell expands `$R` first). Straight-line order only: a
    conditional, a loop or a function body is read as if it ran. A value that is not typed (an unknown `$X`,
    a substitution) leaves the name unknown."""
    words = list(segment)
    while words and (words[0][0] in _ASSIGN_KEYWORDS or words[0][0].startswith("-")) and any(
            _ASSIGN_WORD.match(w) for w, _ in words[1:]):
        words = words[1:]
    if not words or not all(_ASSIGN_WORD.match(w) for w, _ in words):
        return
    for word, source in words:
        name, _, rest = word.partition("=")
        typed = _typed_operand(rest, source.partition("=")[2], env)
        if typed is None or typed[0] is None:
            env.pop(name, None)
        else:
            env[name] = typed[0]


def _root_delete_in_flat(text: str, mark: str = "") -> tuple[str | None, _RootFact | None]:
    """Keep source quote ownership and distinguish possible glob options. -> (verdict, fact): PROVEN /
    POSSIBLE / None, and the first `_RootFact` behind it (a PROVEN root operand, else a home-directory one)."""
    tokens = _shell_tokens(text)
    if tokens is None:
        return None, None
    segment, possible, redirect = [], False, False
    env: dict[str, str] = {}
    fact = home = None
    for word, start, end in [*tokens, (';', len(text), len(text))]:
        source = text[start:end]
        if redirect:
            redirect = False
            continue
        if source == word and any(c in word for c in '<>'):
            redirect = True
            continue
        operator = bool(word) and set(word) <= set(';&|()\n') and (source == word or start == len(text))
        if not operator:
            word = word.replace(mark, '') if mark else word
            if word:
                segment.append((word, source))
            continue
        _note_assignment(segment, env)
        if segment:           # the command a wrapper (`sudo -u x`, `env A=1`, `nohup`, `timeout 5`, `A=1 rm …`) runs
            segment = segment[len(segment) - len(_wrapped_command([w for w, _ in segment])):]
        if segment[:1] and segment[0][0] == 'rm':
            recursive, glob_recursive = False, False
            for option, spelling in segment[1:]:
                if option == '--':
                    break
                active = any(c in '*?[' for _, c in _unquoted_chars(spelling))
                if active:
                    glob_recursive |= _root_glob_may_recurse(spelling.replace(mark, '') if mark else spelling)
                elif option == '--recursive' or (option.startswith('-') and not option.startswith('--')
                                                and 'r' in option.lower()):
                    recursive = True
            facts = [f for f in (_root_fact(w, src, env) for w, src in segment[1:]) if f]
            roots = [f for f in facts if f.kind != 'home']
            if roots:
                if recursive:
                    return 'PROVEN', roots[0]
                possible |= glob_recursive
            elif facts and recursive:
                home = home or facts[0]
        elif (len(segment) > 1 and segment[0][0] == 'find' and any(w == '-delete' for w, _ in segment[2:])):
            found = _root_fact(*segment[1], env)
            if found and found.kind != 'home' and not segment[1][0].endswith('*'):
                return 'PROVEN', found
        segment = []
    return ('POSSIBLE' if possible else None), home


def _script_between(text: str, lo: int, hi: int) -> str:
    """The script a substitution body ``text[lo:hi]`` holds. Inside a backtick pair the shell removes a
    backslash that precedes `$`, a backtick or another backslash BEFORE it reads the body as a script,
    so `\\$(…)` there is a live `$(…)`."""
    inner = text[lo:hi]
    if text[lo - 1:lo] == '`' and text[hi:hi + 1] == '`':
        inner = re.sub(r'\\([\\`$])', r'\1', inner)
    return inner


def _root_delete_scan(command: str) -> tuple[str | None, _RootFact | None, _RootFact | None]:
    """Narrow direct-shell root deletion backstop, independent of directory permission.

    Tokenize rather than matching prose in echo/grep/comments. This is not a shell
    interpreter: wrappers and expansions the substitution owner cannot delimit are outside
    its scope. A command substitution it CAN delimit (`$( … )`, a backtick pair, quoted or
    not) is a command the shell runs, so its body is judged too. A heredoc BODY is data (the
    layout owner finds it): the commands around it are judged, and an UNQUOTED body's own
    substitutions are judged like any other — a `<<` anywhere never makes this abstain.
    """
    if not command:
        return None, None, None
    # A shell text is read in ITS OWN CONTEXT, and a command substitution is a context of its own: a
    # fresh script (word start, no quote) whose comments end at ITS newlines and whose quote characters
    # never open or close a quote of the text around it. So each work item is a RAW source text, and:
    #   1. `shellinput.expansions` — the one owner of "what the shell expands" (single quotes and escapes are
    #      literal there, a comment is skipped to its newline, a backtick pair ends at the next backtick
    #      whatever quotes it holds) — reads the RAW text; its extents are the executable substitutions;
    #   2. each is replaced by one placeholder word, so the text AROUND it is read for quotes, comments and
    #      separators without the substitution's own characters in it;
    #   3. the flat tokenizer judges that outer text; every substitution is queued as a new RAW item;
    #   4. an opener hidden by a continuation (`$` backslash-newline `(`) is invisible to step 1, so the
    #      continuation-joined text is read too and any substitution only it finds is queued as well
    #      (not masked: reading it twice errs toward refusing, never toward admitting).
    # A LIST, never recursion, so nesting depth is unbounded by the interpreter; each body is judged
    # BEFORE any permission level is looked at (the write level returns this verdict alone). An expansion
    # that owner cannot delimit abstains, as it always did.
    pending, possible, fact, home = [command], False, None, None
    while pending:
        # Each text is read with its ANSI-C strings ended where bash ends them (same length, so every
        # extent below still indexes it): `echo $'\'' ; rm -rf / #'` runs the rm.
        original = pending.pop()
        lay = shellinput.layout(original)
        if lay.documents:
            for doc in lay.documents:
                if not doc.quoted:           # bash expands an unquoted body: its substitutions are commands
                    body_text = doc.text(original)
                    pending.extend(_script_between(body_text, *b.body) for b in shellinput.expansions(body_text)[0])
            original = lay.without_documents()
        raw = shellinput.layout(original).literal_shell
        bodies, _unknown = shellinput.expansions(raw, shell=True)
        mark = next((chr(c) for c in range(0xE000, 0xF8FF) if chr(c) not in raw), "\ue000")
        outer, original_outer, last = [], [], 0
        for body in bodies:
            outer.append(raw[last:body.start])
            original_outer.append(original[last:body.start])
            outer.append(mark)
            original_outer.append(mark)
            last = body.end
        outer.append(raw[last:])
        original_outer.append(original[last:])
        outer_text = "".join(outer)
        # Decode against the unmasked source while retaining substitution placeholders.
        decoded = shellinput.decode_ansi_c("".join(original_outer), outer_text)
        text = _join_continuations(decoded, drop_comments=True)[0]
        verdict, found = _root_delete_in_flat(text, mark)
        if verdict == 'PROVEN':
            return verdict, found, home
        home = home or found
        possible |= verdict == 'POSSIBLE'
        extents = {(body.start, body.end) for body in bodies}
        found = [(body.body, raw) for body in bodies]
        if "\\" in raw:                                   # a continuation can hide an opener from step 1
            joined, joined_origin = _join_continuations(raw)
            if joined != raw:
                for body in shellinput.expansions(joined, shell=True)[0]:
                    lo = joined_origin[body.start]
                    hi = (joined_origin[body.end - 1] + 1) if body.end > body.start else lo
                    if (lo, hi) not in extents:
                        first, last_ = body.body
                        found.append(((joined_origin[first] if first < len(joined_origin) else len(raw),
                                       (joined_origin[last_ - 1] + 1) if last_ > first else len(raw)), joined))
        for (lo, hi), source in found:
            pending.append(_script_between(raw, lo, hi))
    return ('POSSIBLE' if possible else None), None, home


def _root_delete_assessment(command: str) -> str | None:
    """PROVEN / POSSIBLE / None; the verdict `cleanupsafety` reads for a saved shell script."""
    return _root_delete_scan(command)[0]


def root_recursive_delete_refusal(command: str) -> str | None:
    """The refusal text for a root deletion the lexical backstop proves (or cannot rule out, for a
    wildcard that may supply the recursive option); None otherwise. A bounded backstop, not a parser or a
    sandbox. It resolves what the command TYPES: the spellings of `/`, a literal path whose `.`/`..` steps
    lead back to `/` (resolved on this host, symlinks followed), and `$R` where `R=/` is assigned earlier in the
    same script text. Unseen, and so admitted: a value from the environment (`$TARGET` never assigned here), a
    symlink that IS the operand's final component, an assignment inside a child script (a substitution body,
    `bash -c`, a saved file) for a delete outside it, a variable built from a substitution, loop variables
    (`for d in /; do rm -rf $d`), and a conditional assignment is read as if it ran. The text says which fact
    it rests on, never more."""
    verdict, fact, _home = _root_delete_scan(command)
    if verdict == 'PROVEN':
        if fact and fact.kind == 'dotdot':
            return prompts.fill(prompts.load_map('root_recursive_delete_resolved')['dotdot'], operand=fact.operand)
        if fact and fact.kind == 'variable':
            return prompts.fill(prompts.load_map('root_recursive_delete_resolved')['variable'],
                                operand=fact.operand, name=fact.name, value=fact.value)
        return prompts.load('root_recursive_delete_refusal')
    if verdict == 'POSSIBLE':
        return prompts.load('work_log_denied')
    return None


def home_recursive_delete_refusal(command: str, level: str) -> str | None:
    """A recursive delete of the HOME directory reached through a variable assigned earlier in the same script
    (`H=~; rm -rf "$H"`, `rm -rf $HOME`). The literal `rm -rf ~` is an external path the path scan already judges
    at `none`/`read`; this is the same fact for the spelling the scan cannot see (`$H` is an unresolved
    expansion to it). At `write` the operator accepted unrestricted paths, so home deletion is their choice."""
    if level == 'write':
        return None
    _verdict, _fact, home = _root_delete_scan(command)
    if home is None:
        return None
    words = prompts.load_map('root_recursive_delete_resolved')
    return prompts.fill(words['home_assigned'] if home.name else words['home_env'], operand=home.operand, name=home.name)


# A directory change is PERSISTED STATE, not a read. In a harness whose shell keeps its working
# directory between calls (cria cannot know which harness it fronts, and no tool contract here says a
# cwd resets — a persistent bash process reproduces it) the NEXT call starts where this one ended,
# and its relative write target — judged here against the workspace — lands there instead. So `cd /m2/repository && ls`
# followed by `echo x > y` wrote into the dependency cache while every guard call said "inside the
# project". An external `cd` therefore gets no read exemption: not for a dependency cache (even with no
# declared roots), not for a declared root, not at level `read`. A target cria cannot place (a
# variable, `~`, `-`, a bare `cd`, extra options) is refused the same way: unknown scope fails closed.
# Judged on the RECOGNISED command word of each top-level command (`_input_commands`, the same lexer
# the input/heredoc owners use; `cd` as an argument, inside a quote or a heredoc body is not one) and
# resolved against the cwd owner (`_follow_cd`, chained). A child shell (`bash -c`, `$( )`, a saved
# script) does not export its cwd, so only the top level (_depth == 0) is judged. Walked: a persistent
# bash, two guard decisions (tests/test_a_directory_change_is_not_a_read.py). BEST-EFFORT AND LEXICAL,
# NOT CONTAINMENT. Residual, not claimed: a `source`d script, a called function, `eval` or `trap` can
# change directory out of sight; a relative `cd name` can be redirected by an inherited CDPATH; and a
# symlink inside the project is lexically internal (the same lexical rule as every write target here). `builtin` dispatches like `command`; `pushd +N`, `popd` and an operand
# starting `-` (`cd -P`, `cd --`, `cd -`) use state this module cannot see, so they are unplaceable.
_CWD_COMMANDS = ("cd", "pushd", "popd")


def _unparsed_names_a_cwd_command(shell: str) -> bool:
    """For a command ``_input_commands`` could not segment (an operator it does not model, such as
    `<(`): is a cwd command still the first word of some segment? Same lexer, same prefix unwrapping."""
    for start, end in _segment_spans(shell):
        spans = _shell_tokens(shell[start:end])
        if spans is None:
            continue
        words = _command_words([w for w, _, _ in spans if not (w and set(w) <= _PUNCT)])
        if words[:1] and words[0] in _CWD_COMMANDS:
            return True
    return False


def _persisted_cwd_refusal(shell: str, workspace: str | None) -> str | None:
    commands = _input_commands(shell)
    if commands is None:
        # Grammar this module does not model, and a directory change in it: scope unknown, fail closed
        # with the module's existing "cannot be established" text. Anything else is not judged here.
        return prompts.load("external_write_unproven") if _unparsed_names_a_cwd_command(shell) else None
    cur = os.path.normpath(os.path.expanduser(workspace)) if workspace else None
    for _start, _end, words, _outputs, _inputs in commands:
        words = _command_words(words)
        if words[:1] and words[0] in _CWD_COMMANDS:
            cur = _follow_cd(words, cur)
            # No known workspace means no known project to stay inside: a recognised directory change
            # is then unplaceable (`is_external` answers True for a rooted path), never a made-up root.
            if cur is None or is_external(cur, workspace):
                return prompts.fill(prompts.load("external_cd_refusal"), cmd=repr(" ".join(words)),
                                    root=f" ({workspace})" if workspace else "")
    return None


def _unproven_read_refusal(external: str, failure: "_ProofFailure", source: str) -> str:
    """The refusal for a read of a harness-declared path inside a command the read proof could not clear:
    it names the part the proof could not verify, in the coder's own source text (``source`` is the
    original command; the proof ran on a same-length projection of it), and why."""
    words = prompts.load_map("inspection_read_proof")
    return prompts.fill(words["header"], path=repr(external), segment=repr(source[failure.start:failure.end]),
                        explanation=prompts.fill(words[failure.reason], word=failure.word))


def command_refusal(command: str, level: str, workspace: str | None, roots=(), *,
                    _cwd="", _depth=0) -> str | None:
    """The refusal for a RAW shell command, or None when allowed — heuristic: refuse when the command
    names an external absolute/``~`` path, weighed against whether it looks like a write. Under
    ``none`` any external path is refused; under ``read`` only an external WRITE is."""
    if not command:
        return None
    # Root deletion and machine-wide harm are independent of external permission. Input execution is
    # judged separately below, never confused with a cat's literal stdin.
    root_delete = root_recursive_delete_refusal(command) or machine_harm_refusal(command)
    if root_delete or level == "write":
        return root_delete
    home_delete = home_recursive_delete_refusal(command, level)
    if home_delete:
        return home_delete
    if _depth > 3:
        return prompts.load('external_write_unproven')
    layout = shellinput.layout(command)
    if layout.error:
        return prompts.load('external_write_unproven')
    cwd = os.path.normpath(os.path.expanduser(workspace)) if _cwd == "" and workspace else _cwd
    scripts, unknown = shellinput.expansions(layout.shell, shell=True)
    if unknown:
        return prompts.load('external_write_unproven')
    outer_shell = shellinput.outer_shell(layout.shell, scripts)
    if scripts:
        commands = _input_commands(outer_shell)
        if commands is None:
            return prompts.load('external_write_unproven')
        for substitution in scripts:
            cur = _cwd_before(commands, outer_shell, substitution.start, cwd)
            refusal = command_refusal(substitution.text(layout.source), level, workspace, roots,
                                      _cwd=cur, _depth=_depth + 1)
            if refusal:
                return refusal
    if layout.documents:
        refusal = _input_refusal(layout, outer_shell, scripts, level, workspace, roots, cwd, _depth)
        if refusal:
            return refusal
    decoded = shellinput.decode_ansi_c(layout.source, outer_shell)
    if decoded != outer_shell:
        # Judge the decoded view as well as the original, while keeping the original
        # coordinate system for heredocs, substitutions and read-proof explanations.
        if _depth == 0:
            moved = _persisted_cwd_refusal(decoded, workspace)
            if moved:
                return moved
        refusal = command_refusal(decoded, level, workspace, roots, _cwd=cwd, _depth=_depth + 1)
        if refusal:
            return refusal
    command = outer_shell
    if _depth == 0:
        moved = _persisted_cwd_refusal(command, workspace)
        if moved:
            return moved
    # An install writes outside the workspace WITHOUT naming a path, so it must be judged before
    # the path scan — which by construction finds nothing to refuse in it.
    installing = install_refusal(command, level, workspace)
    if installing:
        return installing
    # Same class, judged in the same place: a selector that reaches outside the workspace without
    # naming a path, so the scan below can never see it.
    # Judged on the SOURCE (its layout view keeps every substitution): `kill $(lsof -t -i :8081)` IS the selector,
    # and the `outer_shell` above has already replaced its body with an opaque word.
    killing = kill_refusal(layout.source, level)
    if killing:
        return killing
    # A command that changes nothing (shelltool's classifier, generous toward "writes") may read a
    # root the harness declared writable; one that might write there stays under the normal rule.
    proof = _read_proof(command, workspace) if roots else None          # run ONCE; its failure is the evidence below
    read_only = bool(roots) and proof is None
    segments = _segment_spans(command)
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
        # The pattern exemption belongs to the SEGMENT whose command owns the quote: `cp in "/tmp/o";
        # grep x in` must not hide the cp's destination behind the grep that follows it. And a quoted
        # string that is itself a write TARGET (`grep x in > "/tmp/o"`) is a file, never a pattern.
        wstart = m.start() if inside is None else inside - 1
        quoted_write = inside is not None and _is_write_target(command, wstart)
        if inside is not None and not quoted_write and (
                m.start() != inside or _segment_is_text_search(command, segments, m.start())
                or _is_param_value_quote(command, inside)):
            continue
        if _after_unresolved_expansion(command, m.start()):
            continue
        if inside is None and _runs_system_program(command, segments, m.start(), tok):
            continue
        if not is_external(tok, workspace) or _exempt(tok):
            continue
        # A READ of a dependency-artifact cache grounds an installed library's real API (javap a jar,
        # read a module's source); it writes nothing outside the workspace, so allow it even at
        # `none` and keep scanning for a MORE serious external token. A WRITE targeting the cache is
        # not skipped — it falls through and is refused.
        if _is_dependency_cache(tok) and not _is_write_target(command, wstart):
            continue
        # In a network request, a rooted path token is a URL fragment, not a file access — exempt it
        # unless it is an explicit write TARGET (curl -o /etc/x, > /tmp/y), which is a real external write.
        is_write = _is_write_target(command, wstart)
        # A harness-declared root may be READ by a command PROVEN to only read; the write-target
        # checks above/below always run first.
        if read_only and not is_write and _in_declared_root(tok, roots):
            continue
        # The exemption is the NETWORK TOOL's own arguments: the segment that holds it, not every segment of the command
        # (`cat /etc/shadow; curl http://h` reads /etc/shadow), and not a file the tool uploads.
        if (not is_write and not _UPLOAD_BEFORE.search(command[:m.start()])
                and any(s <= m.start() < e and _NETWORK_CMD.search(command[s:e]) for s, e in segments)):
            continue
        # At `read` an external READ is allowed — but it must not END the scan: a later segment may
        # write outside (`cat "/tmp/o/in"; grep x in > /tmp/o/out`), so keep judging every target.
        if level == "read" and not is_write and not _MUTATING_VERB.search(command):
            continue
        external = tok
        ext_is_write = is_write
        break
    if external is None:
        # Nothing ABSOLUTE tripped the scan. A WRITE can still leave the workspace by a relative
        # `..` path, or by an absolute one hidden inside a `bash -c` string; resolve each write target.
        escaped = _escaping_write_target(command, workspace, _cwd, _depth, level=level, roots=roots)
        if isinstance(escaped, _InputRefusal):
            return escaped.message
        if escaped is _UNPROVEN_WRITE:
            return prompts.load('external_write_unproven')
        if escaped is None:
            return None
        return _refusal("Writing", escaped, workspace, roots, level)
    # Under `read` level an external READ is allowed; refuse only when the EXTERNAL TOKEN ITSELF is a
    # write target — NOT when any write verb appears elsewhere (`grep /etc/hosts > local.txt` reads the
    # external file but writes LOCALLY, and must pass; the old whole-command _WRITE_VERB scan false-refused
    # it as "Writing", also misnaming the action).
    if level == "read" and not (ext_is_write or _MUTATING_VERB.search(command)):
        return None
    if _in_declared_root(external, roots):
        # Say exactly what was refused: a write TARGET there, or a command not proven to only read.
        if ext_is_write:
            return _refusal("Writing", external, workspace, roots, level)
        # Reached only with declared roots, a path in one, and no write target: every such token is skipped
        # above while the proof holds, so here the proof FAILED and ``proof`` is its failure.
        assert proof is not None, "a declared-root read reached the unproven branch with a clean proof"
        return _unproven_read_refusal(external, proof, layout.source)
    return _refusal("Writing/reading" if level == "none" else "Writing", external, workspace, roots, level)
