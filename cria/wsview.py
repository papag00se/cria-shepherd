"""What is in the CODER's workspace — answered from facts the HARNESS gathered.

cria is an HTTP server. The harness drives: cria only ever speaks when the harness asks it
something, and it has NO synchronous outbound channel back. It can ask the workspace a question
exactly one way — put a command in the reply it is already sending, and read the answer on the
next request. Everything in this module follows from that one fact.

WHY IT EXISTS. Seventy-four call sites across fourteen modules took a workspace path the harness
announced — a path on the HARNESS's filesystem — and handed it to ``os.path.isdir`` /
``os.walk`` / ``open``, which answer for the machine CRIA runs on. The two are the same machine
only by accident: the likely deployment is cria beside the model server while the harness runs on
someone's workstation. When they differ, every one of those calls answers "nothing there", every
mechanism built on them abstains, and cria degrades to almost nothing while reporting no problem
at all. That is the one failure shape that cannot be noticed from the outside.

HOW IT WORKS.

* **The survey** — one bounded ``python3`` program cria composes and the HARNESS runs, riding
  along on shell commands cria is already sending (a lowered ``write_file``, the completion
  gate). It costs no extra turn, and its output is stripped out of the model's view exactly like
  the gate's sections are: the model sees the result of its own call and nothing else.
* **The conversation** — every synthetic file tool cria lowered is in the message history with
  its path and its bytes. A ``write_file`` proves a file's content; a ``read_file`` result proves
  it too; an ``edit_file`` proves the content CHANGED and is therefore no longer known.
* **Misses** — a question the view cannot answer is recorded, and the next survey asks it. Bodies
  and program lookups both work this way, so the cost is bounded by real demand rather than by a
  guess about what might be wanted.

WHAT IT NEVER DOES. It never touches cria's own filesystem, and it never turns "I do not know"
into "no". Every predicate is three-valued: ``True``, ``False``, ``None``. ``None`` means the
question has not been answered yet, and every caller's safe direction for ``None`` is the one it
already had for an unreadable workspace — abstain, keep the probe, say nothing (#3, #5b).

BOOTSTRAP. The view is empty on the very first request of a session and fills from the first
survey that lands. It is not a race: the completion gate — the heaviest reader — first fires on a
completion claim or every fifteenth turn (measured ten minutes and eleven turns into a walked
run), by which time several surveys have ridden along.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import os
import posixpath
import time
import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- wire format

# Marker opening the survey block appended to a cria-composed command. Everything from this line
# to SURVEY_CLOSE is cria's, never the model's, and is stripped before the result is represented.
SURVEY_OPEN = "___CRIA_SURVEY___"
SURVEY_CLOSE = "___CRIA_SURVEY_END___"
# Marker bracketing the survey inside the COMMAND cria composed, so the same plumbing-strip that
# hides the gate's own scaffolding from the model hides this too. The model never authored either.
SURVEY_CMD_OPEN = "# ___CRIA_SURVEY_CMD___"
SURVEY_CMD_CLOSE = "# ___CRIA_SURVEY_CMD_END___"
_SEC_PREFIX = "___CRIA_SV_"
_SEC_SUFFIX = "___"

# How much of the tree one survey may carry. A task workspace is a few hundred files; a repo with
# an installed dependency tree is tens of thousands, and the whole listing would be cut by the
# harness's own output cap before cria ever saw it — which would be a silent lie about what
# exists. So a directory holding more than FOLD_AT files is FOLDED to a count, and questions
# inside it answer "unknown" rather than "no".
# The listing rides home inside one tool result, which passes through the HARNESS's own output cap.
# Overrun it and the result is cut in transit — and a listing cut in transit is indistinguishable
# from a listing of a smaller repo, so every file past the cut would read as deleted. What does not
# fit is FOLDED (named, with its interior marked unknown) rather than dropped.
#
# 48,000 WAS 4.7x THE CAP IT CLAIMED TO FIT INSIDE. Measured two ways: across 401 real
# harness-truncated results in the captures the retained size is 9,292 min / 10,212 median / 10,223
# p90, and cria's own bound on a tool result (`content_reduce.INLINE_RESULT_MAX_BYTES`) is 9,000.
# Ran the real survey program against all 87 archived run workspaces: 10 of 10 rust and 22 of 35
# ruby workspaces produced a survey over the bound (median 40-49 KB), and this repo surveys at
# 55,289 bytes. Those are the two task families that have been running. A survey cut in transit is
# rejected wholesale by `apply_survey` — correctly — so on those workspaces the view was NEVER
# surveyed, and an unsurveyed view is what `_confirm_completion` fails open on and what makes
# `linterprobe.collect_files` return no probes at all.
#
# The bound is now the same one every other tool result is held to, less room for the survey's other
# sections (bodies, programs, outside paths) and for whatever command it rode home on. Folding
# harder is a real answer — a folded directory is named and its interior reads as unknown, which
# every downstream reader already handles. Being cut in transit is not.
TREE_MAX_ENTRIES = 1200
TREE_MAX_BYTES = 6_000
# The smallest tree budget worth asking for. Below this the survey would carry little more than its
# own markers, and the caller is better off not spending the bytes — see `survey_command(budget=)`.
TREE_MIN_BYTES = 400
FOLD_AT = 400
# When the tree bound is reached, the directories still queued are FOLDED — named, with their
# interiors marked unknown — rather than dropped, so `isdir` stays right and nothing inside them is
# ever answered "no". Past this many even the fold records would not fit, and the listing says
# plainly that it is incomplete.
FOLD_DRAIN_MAX = 400
# Per-survey body budget. Bodies are fetched only for paths a reader actually asked for and could
# not be told (see :meth:`View.read`), so this bounds a real demand, not a guess.
BLOB_FILES_MAX = 8
BLOB_BYTES_MAX = 48_000
# One file may use the whole turn's budget — a 40 KB source file is ordinary, and a judge asked to
# grade it needs the bytes. Anything past this cannot be delivered at all, and the survey SAYS so
# rather than silently skipping it (see the undeliverable note in View.read_bytes).
BLOB_FILE_MAX = BLOB_BYTES_MAX
# Program lookups per survey (``toolpath.resolved`` misses).
PROG_MAX = 24
# Named paths OUTSIDE the workspace tested per survey (dependency caches, install prefixes).
OUTSIDE_MAX = 24

# Only ``.git`` is pruned. Every other "skip this" list in cria belongs to a READER — execcheck
# keeps `vendor` because a PHP repo's deliverables live there, groundtruth excludes it from an
# inventory — and a survey that pre-applied any of them would answer a question it was not asked.
PRUNE_DIRS = (".git",)


# --------------------------------------------------------------------------- the view

@dataclass(frozen=True)
class Entry:
    """One workspace entry, shaped like ``os.DirEntry`` so the readers that used ``os.scandir``
    are unchanged. ``path`` is harness-absolute — the same string the harness's own shell would
    print — because that is what every caller passes back into the view."""

    name: str
    path: str
    _is_dir: bool
    size: int = 0
    mtime: float = 0.0

    def is_dir(self, follow_symlinks: bool = True) -> bool:   # noqa: ARG002 — DirEntry signature
        return self._is_dir

    def is_file(self, follow_symlinks: bool = True) -> bool:  # noqa: ARG002 — DirEntry signature
        return not self._is_dir


def _posix(p) -> str:
    return str(p).replace(os.sep, "/").replace("\\", "/")


class View:
    """The coder's workspace as cria currently knows it. Every answer is a fact somebody
    gathered — from a survey the harness ran, or from a tool call in the conversation."""

    __slots__ = ("root", "_files", "_dirs", "_folded", "_bodies", "_body_generation", "_stale",
                 "_progs", "_outside", "_undeliverable", "_surveyed", "_complete", "_sess",
                 "_survey_generation", "_ran_a_mutator")

    def __init__(self, root: str | None, sess: str = "") -> None:
        self.root: str = _posix(root or "").rstrip("/") if root else ""
        self._files: dict[str, tuple[int, float]] = {}   # rel -> (size, mtime)
        self._dirs: set[str] = set()                     # rel dirs, "" for the root
        self._folded: set[str] = set()                   # rel dirs listed only as a count
        self._bodies: dict[str, bytes] = {}              # rel -> the file's BYTES
        self._body_generation: dict[str, int] = {}       # rel -> survey that supplied those bytes
        self._stale: set[str] = set()                    # rel whose body changed since it was known
        self._progs: dict[str, str] = {}                 # program name -> resolved name ("" = absent)
        # Paths OUTSIDE the workspace the harness was asked about by name — a dependency cache
        # (`~/.m2/repository`), an install prefix. There is no listing of these and there must not
        # be one: cria names the exact path it wants tested, and the survey answers that path.
        self._outside: dict[str, str] = {}               # path -> "d" | "f" | ""
        # Paths the harness was ASKED for and could not hand back — too large for one result, or
        # unreadable — recorded with the size they had when it refused. Without this the reader asks
        # again every turn, the survey refuses again every turn, and the miss list is never empty:
        # measured as a survey riding on EVERY lowered call, forever, for one 36 KB file.
        self._undeliverable: dict[str, int] = {}
        self._surveyed = False
        self._survey_generation = 0
        # A COMMAND THAT COULD HAVE CHANGED ANYTHING RAN, and no survey has landed since. The view
        # still answers about the tree it last saw, which is correct for "what did cria see" and
        # wrong for "what is there now" — and the callers that turn a False into a sentence about the
        # world need to be able to tell the two apart (#11b, #23c).
        self._ran_a_mutator = False
        # Whether the last listing named EVERY file. A survey that hit its own entry bound is still
        # worth having — what it listed is real — but "not listed" stops meaning "not there", and
        # every predicate downgrades accordingly.
        self._complete = True
        self._sess = sess
        # A BODY THE HARNESS ALREADY DELIVERED, CARRIED IN FROM A PRIOR REQUEST. `_bind_workspace_view`
        # builds a brand-new, empty `View` on every incoming request (server.py) — that is correct for
        # the TREE, which the harness re-surveys cheaply and often, but a manifest BODY is asked for,
        # delivered once, and then had nowhere to live: the request that received it answers, and the
        # next `View` starts from `_bodies = {}` again. `build_ruby` (and every other ranked-discovery
        # builder reading a manifest body — package.json, pyproject.toml, pom.xml, ...) re-asks,
        # re-misses, and the coder is told "no command to run them was found" for a project whose own
        # Rakefile the harness handed over, byte for byte, minutes earlier (C38). `_BODY_CACHE` is the
        # session-scoped memory of that delivery — seeded here, kept current by `_set_body` and
        # `note_written`, and invalidated the moment an edit lands (`note_changed`) or a fresh survey's
        # tree disagrees on size (`_drop_stale_bodies`, which runs over `self._bodies` regardless of
        # where an entry came from).
        if sess:
            cached = _BODY_CACHE.get(sess)
            if cached:
                self._bodies.update(cached)

    # -- identity ----------------------------------------------------------

    @property
    def surveyed(self) -> bool:
        """A harness survey has landed for this workspace. False means the view holds only what
        the conversation proved, so most answers are ``None``."""
        return self._surveyed

    @property
    def complete(self) -> bool:
        """The last listing named every file. False when the survey hit its own bound — then a path
        it does not name is UNKNOWN, not absent."""
        return self._complete

    @property
    def usable(self) -> bool:
        """There is a workspace AND something is known about it."""
        return bool(self.root) and (self._surveyed or bool(self._files))

    @property
    def observation_fingerprint(self) -> str | None:
        """A complete, current harness-survey generation of this workspace.

        This is deliberately a fingerprint of the survey's tree records, never a local-disk
        observation and never a tool-call counter.  ``None`` means the survey was incomplete or
        has been overtaken by a possible mutator, so callers cannot turn an old absence into a
        fresh fact.  The ordered encoding includes every fact that makes an absence meaningful.
        """
        if not self._surveyed or not self._complete or self._folded or self._ran_a_mutator:
            return None
        rows = [f"F\t{path}\t{size}\t{mtime!r}" for path, (size, mtime) in sorted(self._files.items())]
        rows.extend(f"D\t{path}" for path in sorted(self._dirs))
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()

    # -- path algebra ------------------------------------------------------

    def rel(self, path) -> str | None:
        """``path`` as a workspace-relative posix path, or None when it is outside the workspace
        (or the workspace is unknown). "" is the root itself."""
        if not self.root:
            return None
        p = _posix(path)
        if not p:
            return None
        if p.startswith("/") or re.match(r"^[A-Za-z]:/", p):
            if p == self.root:
                return ""
            if not p.startswith(self.root + "/"):
                return None
            p = p[len(self.root) + 1:]
        p = posixpath.normpath(p)
        if p in (".", ""):
            return ""
        if p == ".." or p.startswith("../"):
            return None
        return p.lstrip("./") if p.startswith("./") else p

    def abs(self, rel: str) -> str:
        """A workspace-relative path as the harness-absolute string the readers pass around."""
        return self.root if not rel else f"{self.root}/{rel}"

    def _folded_under(self, rel: str) -> bool:
        for d in self._folded:
            if rel == d or rel.startswith(d + "/"):
                return True
        return False

    # -- predicates (three-valued: None means nobody has answered yet) -------

    def isdir(self, path) -> bool | None:
        rel = self.rel(path)
        if rel is None:
            return None
        if rel == "":
            return True if self._surveyed else None
        if rel in self._dirs or rel in self._folded:
            return True
        if rel in self._files:
            return False
        if not self._surveyed or not self._complete or self._folded_under(rel):
            return None
        return False

    def isfile(self, path) -> bool | None:
        rel = self.rel(path)
        if rel is None:
            return None
        if rel in self._files:
            return True
        if rel in self._dirs or rel in self._folded:
            return False
        if not self._surveyed or not self._complete or self._folded_under(rel):
            return None
        return False

    def exists(self, path) -> bool | None:
        d = self.isdir(path)
        if d:
            return True
        f = self.isfile(path)
        if f:
            return True
        return None if (d is None or f is None) else False

    def size(self, path) -> int | None:
        rel = self.rel(path)
        if rel is None or rel not in self._files:
            return None
        return self._files[rel][0]

    def mtime(self, path) -> float | None:
        rel = self.rel(path)
        if rel is None or rel not in self._files:
            return None
        return self._files[rel][1]

    # -- content -----------------------------------------------------------

    def read(self, path) -> str | None:
        """The file's text, or None when cria has not been told it.

        A miss is REMEMBERED: the next survey carries a read for this path, so a reader that asks
        the same question next turn gets an answer instead of the same silence."""
        raw = self.read_bytes(path)
        return None if raw is None else raw.decode("utf-8", "replace")

    def request_current_body(self, path) -> None:
        """Put ``path`` on the next survey even if a prior survey cached its bytes."""
        rel = self.rel(path)
        if rel is not None:
            want_body(self._sess, rel)

    def read_current_survey(self, path) -> str | None:
        """Text only when this view's latest survey carried these exact bytes."""
        rel = self.rel(path)
        if rel is None or self._body_generation.get(rel) != self._survey_generation:
            return None
        raw = self._bodies.get(rel)
        return None if raw is None else raw.decode("utf-8", "replace")

    def read_bytes(self, path) -> bytes | None:
        """The file's BYTES, or None when cria has not been told them.

        Bytes, not text, because some readers must answer "is this a PNG" — and a decode with
        ``errors="replace"`` destroys exactly the leading bytes that answer it. A judge handed a
        chart.png used to be told its size and its format; through a lossy round trip it was told
        only "binary data", which is less than cria knows."""
        rel = self.rel(path)
        if rel is None:
            return None
        if rel in self._bodies and rel not in self._stale:
            return self._bodies[rel]
        # ASKED AND REFUSED, AT THIS SIZE. Re-asking would spend a survey a turn on a question with
        # a known answer. The moment the file changes size it is a different question and is asked
        # again, so a file the coder trims back into range is not written off for good.
        entry = self._files.get(rel)
        if rel in self._undeliverable and entry and entry[0] == self._undeliverable[rel]:
            return None
        if self.isfile(path) is not False:
            want_body(self._sess, rel)
        return None

    # -- listing -----------------------------------------------------------

    def listdir(self, path=".") -> list[str] | None:
        """Entry names directly under ``path``, or None when the directory is unknown or folded."""
        rel = self.rel(path)
        if rel is None or not self._surveyed:
            return None
        if rel in self._folded or self._folded_under(rel):
            return None
        if rel != "" and rel not in self._dirs:
            return None
        pre = "" if rel == "" else rel + "/"
        n = len(pre)
        names = {p[n:].split("/", 1)[0] for p in self._files if p.startswith(pre) and "/" not in p[n:]}
        names |= {d[n:] for d in (self._dirs | self._folded)
                  if d.startswith(pre) and d != rel and "/" not in d[n:]}
        return sorted(names)

    def scandir(self, path=".") -> list[Entry] | None:
        """``os.scandir``-shaped entries, or None when the directory is unknown or folded."""
        names = self.listdir(path)
        if names is None:
            return None
        rel = self.rel(path) or ""
        out: list[Entry] = []
        for name in names:
            child = f"{rel}/{name}" if rel else name
            isd = child in self._dirs or child in self._folded
            sz, mt = self._files.get(child, (0, 0.0))
            out.append(Entry(name=name, path=self.abs(child), _is_dir=isd, size=sz, mtime=mt))
        return out

    def walk(self, top=".", skip_names=(), skip_prefixes=(),
             skip_hidden: bool = False) -> list[tuple[str, list[str], list[str]]] | None:
        """``os.walk``-shaped triples rooted at ``top`` (dirpath harness-absolute), or None when
        the subtree is unknown. Folded directories appear as a dirname and yield no triple of
        their own — a reader that recurses into one gets nothing, never a wrong empty answer,
        because :meth:`listdir` on it is None.

        THE PRUNING IS DONE HERE, not by the caller. ``os.walk`` lets a reader prune by assigning to
        ``dirnames``, and every one of cria's walks used that; a list of triples cannot be pruned
        that way, and a caller that filters afterwards has already descended. So the exclusions come
        in as arguments and are applied while walking: ``skip_names`` are directory NAMES at any
        depth (`node_modules`), ``skip_prefixes`` are workspace-relative PATHS (`vendor/bundle`),
        and ``skip_hidden`` drops dot-directories."""
        start = self.rel(top)
        if start is None or not self._surveyed:
            return None
        if start != "" and start not in self._dirs:
            return None
        names, prefixes = set(skip_names or ()), tuple(skip_prefixes or ())
        out: list[tuple[str, list[str], list[str]]] = []
        stack = [start]
        while stack:
            cur = stack.pop(0)
            if cur in self._folded:
                continue
            pre = "" if cur == "" else cur + "/"
            n = len(pre)
            files = sorted(p[n:] for p in self._files if p.startswith(pre) and "/" not in p[n:])
            subs = sorted(d[n:] for d in (self._dirs | self._folded)
                          if d.startswith(pre) and d != cur and "/" not in d[n:])
            keep = [x for x in subs
                    if x not in names
                    and not (skip_hidden and x.startswith("."))
                    and not any(f"{pre}{x}" == p or f"{pre}{x}".startswith(p + "/")
                                for p in prefixes)]
            out.append((self.abs(cur), keep, files))
            stack = [f"{pre}{x}" for x in keep] + stack
        return out

    def files(self) -> list[Entry] | None:
        """Every file the survey listed, or None when nothing has been surveyed."""
        if not self._surveyed:
            return None
        return [Entry(name=posixpath.basename(r), path=self.abs(r), _is_dir=False,
                      size=s, mtime=m) for r, (s, m) in sorted(self._files.items())]

    def undeliverable_size(self, path) -> int | None:
        """The known size of a body a survey could not deliver, if it is still current.

        This is deliberately distinct from an ordinary ``read_bytes`` miss: that miss queued a
        body demand for the next survey, while this one was already answered with an explicit
        refusal.  A changed size is a new question and must be allowed to queue again.
        """
        rel = self.rel(path)
        entry = self._files.get(rel) if rel is not None else None
        size = self._undeliverable.get(rel) if rel is not None else None
        return size if entry is not None and entry[0] == size else None

    def body_pending(self, path) -> bool:
        """Whether a body demand for ``path`` is queued for the next survey.

        Callers use this after :meth:`read_bytes` returned ``None``.  Known-undeliverable
        bodies are not pending: their survey already gave the only answer available at this size.
        """
        rel = self.rel(path)
        return bool(rel and rel in _BODY_MISSES.get(self._sess, ()))

    @property
    def undeliverable(self) -> list[str]:
        """Files the harness was asked for and could not hand back in one result. Their existence
        and size are known; their contents are not, and cria has no way to get them."""
        return sorted(self._undeliverable)

    @property
    def folded(self) -> list[str]:
        """Directories listed only as a count — questions inside them answer ``None``."""
        return sorted(self._folded)

    def reroot(self, want: str) -> "View":
        """This view seen from ``want`` instead of its own root — an EMPTY view when ``want`` is not
        inside it, because answering a question about a directory nobody looked at from a survey of
        a different tree is a false fact, not a convenience."""
        sub = self.rel(want)
        if sub is None:
            return View(want, self._sess)
        return _subview(self, sub)

    # -- paths outside the workspace ----------------------------------------

    def outside_kind(self, path: str) -> str | None:
        """``"d"``, ``"f"`` or ``""`` for a path the workspace does not contain, and None until the
        harness has been asked about it. Used for the fixed tables of dependency-cache and install
        locations — never for a path cria made up."""
        if not path:
            return None
        key = _posix(path)
        if key in self._outside:
            return self._outside[key]
        want_outside(self._sess, key)
        return None

    # -- the coder's PATH ---------------------------------------------------

    def listed_everything(self, path: str = "") -> bool:
        """Could the last survey have named EVERY entry at ``path``?

        The absence half of `listdir`/`scandir`/`walk`. Those three return the files cria KNOWS
        about, which is the right answer for a caller checking things it can see — and the wrong one
        for a caller reading a short list as a complete one. `isfile`/`isdir` already refuse to
        answer under the same conditions; this is the same guard for a listing.

        Measured on a real 420-file root, which the survey folds to a count: `listdir` answered `[]`,
        so both model-facing `list_dir` tools said "empty directory", `_workspace_is_empty` answered
        True, and the server's workspace listing — whose own comment says it "may not lie by
        omission" — rendered nothing (#5b, #11b, #23c)."""
        if not self._surveyed or not self._complete:
            return False
        return not self._folded_under(self.rel(path) if path else "")

    def program(self, name: str) -> str | None:
        """The executable the CODER's shell resolves ``name`` to, "" when it resolves nothing, and
        None when nobody has asked yet. A miss is remembered for the next survey."""
        if not name:
            return None
        if name in self._progs:
            return self._progs[name] or ""
        want_program(self._sess, name)
        return None

    # -- ingestion ----------------------------------------------------------

    def _ingest_tree(self, body: str, complete: bool = True) -> None:
        self._files.clear()
        self._dirs.clear()
        self._folded.clear()
        self._complete = complete
        for line in body.splitlines():
            if not line:
                continue
            kind, _, rest = line.partition("\t")
            if kind == "D":
                if rest:
                    self._dirs.add(rest)
            elif kind == "X":
                _count, _, d = rest.partition("\t")
                if d:
                    self._dirs.add(d)
                    self._folded.add(d)
                else:
                    # THE ROOT ITSELF WAS FOLDED, and this record used to be thrown away because its
                    # path is the empty string. The survey emits `X\t<count>\t` for a root holding
                    # more than FOLD_AT files and then stops — so `_files`, `_dirs` and `_folded` all
                    # stayed empty while `_surveyed` and `_complete` stayed True. Every predicate
                    # then answered FALSE rather than None, and `groundtruth.workspace_inventory`
                    # told every judge, the planner and the briefing writer:
                    #
                    #   "WORKSPACE FILES in <root>: none — the workspace has no files at judging time."
                    #
                    # Reproduced on a 420-file root: `isfile(main.py)` returned False, not None. A
                    # bound that turns "I could not look" into "it is not there" is the false fact
                    # this class of guard exists to prevent (#5b, #11b, #23c).
                    self._complete = False
            elif kind == "F":
                mt, _, rest2 = rest.partition("\t")
                sz, _, rel = rest2.partition("\t")
                if not rel:
                    continue
                try:
                    self._files[rel] = (int(sz), float(mt))
                except ValueError:
                    self._files[rel] = (0, 0.0)
        self._surveyed = True
        self._ran_a_mutator = False
        self._drop_stale_bodies()

    def _drop_stale_bodies(self) -> None:
        """Forget any remembered body the fresh listing contradicts.

        A body cria holds came from a write it lowered, a read it lowered, or an earlier survey. The
        listing that just arrived is newer than all of them, and it carries each file's real size —
        so a length that disagrees is proof the file has moved on, and a path the listing does not
        name at all is proof it is gone. Holding either would be quoting a file back to a judge as
        it was, under a heading saying what it IS (#5b). What is dropped is simply re-asked."""
        for rel in list(self._bodies):
            entry = self._files.get(rel)
            if entry is None or entry[0] != len(self._bodies[rel]):
                del self._bodies[rel]
                self._body_generation.pop(rel, None)
                self._stale.discard(rel)

    def _ingest_blob(self, body: str) -> None:
        cur_rel: str | None = None
        buf: list[str] = []
        for line in body.splitlines():
            if line.startswith("!"):
                if cur_rel is not None:
                    self._set_body(cur_rel, "\n".join(buf))
                cur_rel, buf = None, []
                enc, _, size = line[1:].partition("\t")
                try:
                    self._undeliverable[base64.b64decode(enc.encode()).decode("utf-8", "replace")] \
                        = int(size)
                except Exception:                     # noqa: BLE001 — a malformed record is no record
                    pass
            elif line.startswith("@"):
                if cur_rel is not None:
                    self._set_body(cur_rel, "\n".join(buf))
                buf = []
                try:
                    cur_rel = base64.b64decode(line[1:].encode()).decode("utf-8", "replace")
                except Exception:                     # noqa: BLE001 — a malformed header ends the file
                    cur_rel = None
            elif cur_rel is not None:
                buf.append(line)
        if cur_rel is not None:
            self._set_body(cur_rel, "\n".join(buf))

    def _set_body(self, rel: str, b64: str) -> None:
        try:
            raw = base64.b64decode(b64.encode(), validate=False)
        except Exception:                             # noqa: BLE001 — undecodable is simply unknown
            self._bodies.pop(rel, None)               # never leave an OLDER body standing in for it
            self._body_generation.pop(rel, None)
            self._stale.add(rel)
            _forget_body(self._sess, rel)
            return
        self._bodies[rel] = raw
        self._body_generation[rel] = self._survey_generation
        self._stale.discard(rel)
        self._undeliverable.pop(rel, None)
        # THE DELIVERY OUTLIVES THIS REQUEST (C38). This survey answered a body a builder wanted; the
        # `View` that holds it dies with this HTTP request, so the fact of having been told must be
        # kept somewhere that does not.
        _remember_body(self._sess, rel, raw)

    def _ingest_outside(self, body: str) -> None:
        for line in body.splitlines():
            path, _, kind = line.partition("\t")
            if path:
                self._outside[path] = kind

    def _ingest_progs(self, body: str) -> None:
        for line in body.splitlines():
            name, _, resolved = line.partition("\t")
            if name:
                self._progs[name] = resolved

    def note_written(self, path, content: str) -> None:
        """cria lowered a whole-content write for this path and the harness reported it landed:
        the bytes ARE the file until something else changes it."""
        rel = self.rel(path)
        if rel is None:
            return
        raw = content if isinstance(content, bytes) else content.encode("utf-8", "replace")
        self._bodies[rel] = raw
        self._body_generation.pop(rel, None)  # a coder tool result is not this gate's survey
        self._stale.discard(rel)
        self._undeliverable.pop(rel, None)
        _remember_body(self._sess, rel, raw)  # this replaces a session-cached body if there was one
        prev = self._files.get(rel)
        # A FILE CRIA JUST WATCHED BEING WRITTEN IS THE NEWEST FILE IN THE WORKSPACE. A brand-new
        # path has no previous mtime, and epoch is not "unknown" here — it sorts LAST in every
        # newest-first inventory view, hiding the file the coder wrote this turn from consumers that
        # use recency as signal. cria knows when this happened: now.
        self._files[rel] = (len(raw), prev[1] if prev else time.time())
        self._dirs.discard(rel)
        for d in _parents(rel):
            self._dirs.add(d)

    def note_read(self, path, content: str) -> None:
        """A whole-file read result — the same proof as a write, from the other direction."""
        self.note_written(path, content)

    @property
    def may_have_changed(self) -> bool:
        """Has something run that could have changed the workspace since the last survey landed?

        A survey rides along on a cria-composed write/edit/list, so a stretch of the coder's own
        `exec_command`s moves the disk while the view stands still. `bundle install` put four gems in
        vendor/bundle at 16:56, no survey followed, and cria went on telling the coder `eu_countries`
        is "not installed anywhere — this project has no Gemfile.lock, no vendor/ and no .bundle/"
        (shipping-rates-rb x ternary-bonsai 1787442206, six times, while the coder's own `ls` had
        just listed the gems)."""
        return self._ran_a_mutator

    def note_a_mutator_ran(self) -> None:
        """A command that could have changed the workspace ran; the survey is now behind the disk."""
        self._ran_a_mutator = True

    def note_changed(self, path) -> None:
        """An edit landed. cria knows the file changed and does NOT know what it now holds, which
        is a different thing from knowing nothing at all: existence survives, the body does not."""
        rel = self.rel(path)
        if rel is None:
            return
        self._stale.add(rel)
        # A CACHED BODY FROM A PRIOR REQUEST MUST NOT SURVIVE AN EDIT (C38). `_BODY_CACHE` keeps a
        # delivered body alive past this request; without this, a manifest edited between two gates
        # would have the NEXT `View` seed itself from the pre-edit bytes, straight past the very
        # mechanism (`_stale`) that exists to stop a changed file from being read as its old self.
        _forget_body(self._sess, rel)
        # UNKNOWN SIZE IS NOT ZERO BYTES. The docstring above is exactly right about the BODY and was
        # silently wrong about the SIZE: an edit to a path the last survey did not name — created by
        # the coder's own shell, by `cargo new`, or living inside a folded directory — was recorded
        # as `0`, and the workspace inventory then printed `app.py (0 B)` under a header calling
        # itself on-disk ground truth. `read()` correctly answers None for the same file; the size
        # has to as well (#23c).
        self._files.setdefault(rel, (None, time.time()))


def _parents(rel: str) -> list[str]:
    out, cur = [], rel
    while "/" in cur:
        cur = cur.rsplit("/", 1)[0]
        out.append(cur)
    return out


class DirectView(View):
    """A view answered straight from the process's OWN filesystem.

    THIS IS NOT FOR PRODUCTION and nothing in ``cria/`` constructs one. It exists for the case where
    the workspace genuinely is on this machine — a test that builds a real directory and calls the
    code that inspects it. Binding one lets every such test exercise the real reader logic (the
    walks, the exclusions, the tri-state handling) without also standing up a harness.

    It is a separate class rather than a flag on :class:`View` on purpose: there is no configuration
    that turns the production view into this one, so no deployment can drift into reading cria's
    disk because a setting was wrong.
    """

    def __init__(self, root: str | None = None, sess: str = "") -> None:
        super().__init__(root or "/", sess)
        self._surveyed = True
        self._ran_a_mutator = False

    def rel(self, path) -> str | None:
        p = _posix(path)
        return p or None

    def abs(self, rel: str) -> str:
        return rel

    def isdir(self, path) -> bool | None:
        return os.path.isdir(str(path)) if path else None

    def isfile(self, path) -> bool | None:
        return os.path.isfile(str(path)) if path else None

    def exists(self, path) -> bool | None:
        return os.path.exists(str(path)) if path else None

    def size(self, path) -> int | None:
        try:
            return os.stat(str(path)).st_size
        except OSError:
            return None

    def mtime(self, path) -> float | None:
        try:
            return os.stat(str(path)).st_mtime
        except OSError:
            return None

    def read(self, path) -> str | None:
        raw = self.read_bytes(path)
        return None if raw is None else raw.decode("utf-8", "replace")

    def read_bytes(self, path) -> bytes | None:
        try:
            with open(str(path), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def listdir(self, path=".") -> list[str] | None:
        try:
            return sorted(os.listdir(str(path)))
        except OSError:
            return None

    def scandir(self, path=".") -> list[Entry] | None:
        try:
            entries = sorted(os.scandir(str(path)), key=lambda e: e.name)
        except OSError:
            return None
        out: list[Entry] = []
        for e in entries:
            try:
                isd = e.is_dir(follow_symlinks=False)
                st = e.stat(follow_symlinks=False)
                out.append(Entry(e.name, e.path, isd, st.st_size, st.st_mtime))
            except OSError:
                continue
        return out

    def walk(self, top=".", skip_names=(), skip_prefixes=(),
             skip_hidden: bool = False) -> list[tuple[str, list[str], list[str]]] | None:
        if not os.path.isdir(str(top)):
            return None
        names, prefixes = set(skip_names or ()), tuple(skip_prefixes or ())
        out = []
        for d, sub, files in os.walk(str(top)):
            rel = os.path.relpath(d, str(top)).replace(os.sep, "/")
            rel = "" if rel == "." else rel
            sub[:] = sorted(x for x in sub
                            if x not in names
                            and not (skip_hidden and x.startswith("."))
                            and not any((f"{rel}/{x}" if rel else x) == p
                                        or (f"{rel}/{x}" if rel else x).startswith(p + "/")
                                        for p in prefixes))
            out.append((d, list(sub), sorted(files)))
        return out

    def files(self) -> list[Entry] | None:
        return None

    def program(self, name: str) -> str | None:
        import re as _re
        import shutil as _shutil
        if not name:
            return None
        if _shutil.which(name):
            return name
        pat = _re.compile(rf"^{_re.escape(name)}[0-9][0-9.]*$")
        for d in (os.environ.get("PATH") or "").split(os.pathsep):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for e in names:
                if pat.match(e) and os.access(os.path.join(d, e), os.X_OK):
                    return e
        return ""

    def outside_kind(self, path: str) -> str | None:
        t = os.path.expanduser(str(path or ""))
        return "d" if os.path.isdir(t) else ("f" if os.path.isfile(t) else "")

    def reroot(self, want: str) -> "View":
        return self          # every path is already answered directly; there is nothing to re-root


# --------------------------------------------------------------------------- the request's view

_CURRENT: contextvars.ContextVar[View | None] = contextvars.ContextVar("cria_wsview", default=None)


def bind(view: View | None):
    """Make ``view`` the answer to :func:`current` for this request. Returns the token to reset
    with. A ContextVar rather than a module global because cria serves requests on parallel
    threads (``ThreadingHTTPServer``) and two sessions must never see each other's workspace."""
    return _CURRENT.set(view)


def unbind(token) -> None:
    try:
        _CURRENT.reset(token)
    except ValueError:                                # set in another context — nothing to reset
        pass


def current(root=None) -> View:
    """The view bound to this request, or an EMPTY view when there is none — never cria's disk.

    When ``root`` is given it must match the bound view's root: a caller asking about a different
    tree gets an empty view, because answering it from this workspace's survey would be a false
    fact about a directory nobody looked at."""
    v = _CURRENT.get()
    if v is None:
        return View(_posix(root or "") or None)
    if root:
        want = _posix(root).rstrip("/")
        if want != v.root:
            return v.reroot(want)
    return v


def _subview(v: View, sub: str) -> View:
    """``v`` re-rooted at one of its own subdirectories, so a caller that legitimately works one
    directory down (``probediscovery.inventory`` on a nested project) keeps every surveyed fact
    instead of losing them to a root mismatch."""
    out = View(v.abs(sub), v._sess)
    pre = sub + "/" if sub else ""
    n = len(pre)
    out._files = {p[n:]: t for p, t in v._files.items() if p.startswith(pre)}
    out._dirs = {d[n:] for d in v._dirs if d.startswith(pre)}
    out._folded = {d[n:] for d in v._folded if d.startswith(pre)}
    out._bodies = {p[n:]: b for p, b in v._bodies.items() if p.startswith(pre)}
    out._body_generation = {p[n:]: g for p, g in v._body_generation.items() if p.startswith(pre)}
    out._stale = {p[n:] for p in v._stale if p.startswith(pre)}
    out._progs = v._progs
    out._surveyed = v._surveyed
    out._survey_generation = v._survey_generation
    # THE BOUND FLAG TRAVELS WITH THE SUBTREE. `_complete` defaults True on a fresh View, so a
    # subview of an INCOMPLETE view used to answer False where its parent answered None — the
    # three-valued contract this class exists for, undone by a missing field copy. `sub` itself
    # being folded is the same loss by another door: "src" does not start with "src/", so the
    # marker for the directory being rerooted into never matched and its interior read as absent.
    out._complete = v._complete and sub not in v._folded
    out._undeliverable = {p[n:]: size for p, size in v._undeliverable.items() if p.startswith(pre)}
    out._outside = dict(v._outside)
    return out


# --------------------------------------------------------------------------- outstanding questions

# What the view was asked and could not answer, per session. These are cria's OWN notes about its
# own ignorance — the one kind of state this module keeps — and they are what the next survey
# asks. Bounded like every other per-session store in cria.
_BODY_MISSES: dict[str, list[str]] = {}
_PROG_MISSES: dict[str, list[str]] = {}
_OUTSIDE_MISSES: dict[str, list[str]] = {}
_MISS_MAX = 64

# A body the harness ALREADY DELIVERED, kept past the one request that received it (C38). Every
# `View` is a fresh, empty object per request (`server.py:_bind_workspace_view`) — by design for
# the tree, which is cheap to re-ask, but a manifest body is asked for on a miss and delivered once,
# and had no session-scoped home to survive into the NEXT request's `View`. Bounded the same way
# every other per-session store in this module is: a cap per session, and the whole store cleared if
# too many sessions accumulate (a stuck session is the failure mode, not a slow memory leak).
_BODY_CACHE: dict[str, dict[str, bytes]] = {}
_BODY_CACHE_MAX_FILES = 64            # per session — mirrors BLOB_FILES_MAX × a few surveys' worth
_BODY_CACHE_MAX_BYTES = 2_000_000     # per session — generous for manifests, still bounded


def _remember_body(sess: str, rel: str, raw: bytes) -> None:
    """A body the harness just handed over — via a survey blob or a lowered write/read cria watched
    land — outlives this one request. Overwrites any earlier bytes for the same path: the newest
    delivery is always the truth, whichever door it came through."""
    if not sess or not rel:
        return
    if len(_BODY_CACHE) > 512:
        _BODY_CACHE.clear()
    bucket = _BODY_CACHE.setdefault(sess, {})
    bucket.pop(rel, None)          # re-insert at the end — dicts evict oldest-first below
    bucket[rel] = raw
    while len(bucket) > _BODY_CACHE_MAX_FILES:
        bucket.pop(next(iter(bucket)))
    total = sum(len(b) for b in bucket.values())
    while total > _BODY_CACHE_MAX_BYTES and len(bucket) > 1:
        total -= len(bucket.pop(next(iter(bucket))))


def _forget_body(sess: str, rel: str) -> None:
    """An edit landed, or a survey could not decode this path's bytes: whatever cria cached for it
    is no longer known to be current, and must not outlive the change into a later request."""
    if not sess or not rel:
        return
    bucket = _BODY_CACHE.get(sess)
    if bucket:
        bucket.pop(rel, None)


def _remember(store: dict[str, list[str]], sess: str, item: str) -> None:
    if not sess or not item:
        return
    if len(store) > 512:
        store.clear()
    q = store.setdefault(sess, [])
    if item in q:
        return
    q.append(item)
    del q[:-_MISS_MAX]


def want_body(sess: str, rel: str) -> None:
    _remember(_BODY_MISSES, sess, rel)


def want_program(sess: str, name: str) -> None:
    _remember(_PROG_MISSES, sess, name)


def want_outside(sess: str, path: str) -> None:
    _remember(_OUTSIDE_MISSES, sess, path)


def pending(sess: str) -> tuple[list[str], list[str], list[str]]:
    return (list(_BODY_MISSES.get(sess) or []), list(_PROG_MISSES.get(sess) or []),
            list(_OUTSIDE_MISSES.get(sess) or []))


def clear_pending(sess: str, bodies: list[str], progs: list[str], outside: list[str]) -> None:
    """Drop the questions a survey has just been composed for — asking again next turn would
    spend the budget re-asking what is already in flight."""
    for store, asked in ((_BODY_MISSES, bodies), (_PROG_MISSES, progs), (_OUTSIDE_MISSES, outside)):
        q = store.get(sess)
        if q:
            store[sess] = [x for x in q if x not in set(asked)]


# --------------------------------------------------------------------------- the survey command

_SURVEY_PY = r'''
import base64, os, sys
W = sys.stdout.write
TREE_MAX, TREE_BYTES, FOLD_AT, PRUNE = {tree_max}, {tree_bytes}, {fold_at}, {prune!r}
BLOB_FILES, BLOB_BYTES, BLOB_FILE = {blob_files}, {blob_bytes}, {blob_file}
WANT = {want!r}
PROGS = {progs!r}
OUTSIDE = {outside!r}
root = os.getcwd()
W("{open}\n")
W("{sec}meta{suf}\n")
W("root\t%s\n" % root)
W("{sec}tree{suf}\n")
n = 0
nrec = 0
spent = 0
complete = 1
def EMIT(line):
    global nrec, spent, complete
    # One bound owns every tree record, including the queued-directory drain below. Previously the
    # main walk stopped at TREE_BYTES and the drain emitted hundreds more records anyway; the harness
    # cut the block, so its declared count could never match what arrived.
    if spent + len(line) > TREE_BYTES:
        complete = 0
        return False
    W(line)
    nrec += 1
    spent += len(line)
    return True
stack = [""]
while stack and n < TREE_MAX and spent < TREE_BYTES:
    cur = stack.pop(0)
    d = os.path.join(root, cur) if cur else root
    try:
        entries = sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        continue
    subs, files = [], []
    for e in entries:
        try:
            isd = e.is_dir(follow_symlinks=False)
        except OSError:
            continue
        (subs if isd else files).append(e)
    if len(files) > FOLD_AT:
        EMIT("X\t%d\t%s\n" % (len(files), cur))
        continue
    for e in subs:
        if e.name in PRUNE:
            continue
        rel = (cur + "/" + e.name) if cur else e.name
        EMIT("D\t%s\n" % rel)
        stack.append(rel)
        n += 1
    for e in files:
        rel = (cur + "/" + e.name) if cur else e.name
        try:
            st = e.stat(follow_symlinks=False)
            EMIT("F\t%.0f\t%d\t%s\n" % (st.st_mtime, st.st_size, rel))
        except OSError:
            EMIT("F\t0\t0\t%s\n" % rel)
        n += 1
        if n >= TREE_MAX or spent >= TREE_BYTES:
            # THE BOUND MEANS UNKNOWN, NOT ABSENT. Breaking here leaves this directory already
            # popped off the stack and the rest of its files unlisted, with no `X` record naming
            # it — and `complete` stayed 1, so `View.isfile` answered FALSE for a file that
            # exists and `listed_everything` told every judge "This list is complete — a file not
            # listed here does not exist in the workspace." Reproduced on a 61-file tree at the
            # budget a gate-carried survey actually gets: 17 records emitted, complete 1,
            # isfile('pkg/file_60.py') -> False. Same defect the root-fold branch was written to
            # fix, one loop further in (#5b, #11b).
            complete = 0
            EMIT("X\t0\t%s\n" % cur)
            break
if stack and (n >= TREE_MAX or spent >= TREE_BYTES):
    complete = 0                      # queued directories nobody will walk — same reason as above
for rel in stack[:{drain_max}]:
    EMIT("X\t0\t%s\n" % rel)
if len(stack) > {drain_max}:
    complete = 0
W("{sec}blob{suf}\n")
bspent, taken = 0, 0
for rel in WANT:
    if taken >= BLOB_FILES or bspent >= BLOB_BYTES:
        break
    p = os.path.join(root, rel)
    try:
        sz = os.path.getsize(p)
    except OSError:
        W("!%s\t-1\n" % base64.b64encode(rel.encode()).decode())
        continue
    if sz > BLOB_FILE:
        W("!%s\t%d\n" % (base64.b64encode(rel.encode()).decode(), sz))
        continue
    try:
        with open(p, "rb") as fh:
            raw = fh.read(BLOB_FILE)
    except OSError:
        W("!%s\t%d\n" % (base64.b64encode(rel.encode()).decode(), sz))
        continue
    W("@%s\n" % base64.b64encode(rel.encode()).decode())
    W(base64.b64encode(raw).decode() + "\n")
    bspent += len(raw)
    taken += 1
W("{sec}outside{suf}\n")
for q in OUTSIDE:
    t = os.path.expanduser(q)
    k = "d" if os.path.isdir(t) else ("f" if os.path.isfile(t) else "")
    W("%s\t%s\n" % (q, k))
W("{sec}progs{suf}\n")
path = os.environ.get("PATH", "")
for name in PROGS:
    hit = ""
    for d in path.split(os.pathsep):
        c = os.path.join(d, name)
        if os.path.isfile(c) and os.access(c, os.X_OK):
            hit = name
            break
    if not hit:
        import re as _re
        pat = _re.compile(r"^" + _re.escape(name) + r"[0-9][0-9.]*$")
        for d in path.split(os.pathsep):
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for e in sorted(names):
                if pat.match(e) and os.access(os.path.join(d, e), os.X_OK):
                    hit = e
                    break
            if hit:
                break
    W("%s\t%s\n" % (name, hit))
W("{sec}done{suf}\n")
W("entries\t%d\n" % nrec)
W("complete\t%d\n" % complete)
W("{close}\n")
'''

_HEREDOC = "__CRIA_SV_PY__"


def survey_command(sess: str = "", *, cd: str = "", budget: int | None = None) -> str:
    """One shell block the HARNESS runs to answer everything the view could not.

    ``python3`` is not a new dependency: cria's lowered ``write_file`` has always been a
    ``python3`` heredoc, so a harness that cannot run this could never have written a file
    either. The program is fed on stdin rather than through ``-c``, so nothing in it competes
    with the surrounding command's quoting and there is no argv length to overflow.

    The whole block is wrapped so it can be appended to a command cria already composed without
    changing that command's exit status — the caller's result must read exactly as it would have.

    ``budget`` is how many bytes of TREE this particular ride home can afford. A caller that is
    already spending most of the result on something else — the gate, whose probe sections divide a
    shared budget — passes what is left, and the survey folds to fit instead of being cut in transit.
    Omitted, the survey takes :data:`TREE_MAX_BYTES`, which is one ordinary tool result's worth.
    """
    bodies, progs, outside = pending(sess)
    bodies, progs, outside = bodies[:BLOB_FILES_MAX], progs[:PROG_MAX], outside[:OUTSIDE_MAX]
    clear_pending(sess, bodies, progs, outside)
    body = _SURVEY_PY.format(
        tree_max=TREE_MAX_ENTRIES, tree_bytes=max(int(budget), TREE_MIN_BYTES) if budget else TREE_MAX_BYTES,
        fold_at=FOLD_AT,
        drain_max=FOLD_DRAIN_MAX, prune=set(PRUNE_DIRS),
        blob_files=BLOB_FILES_MAX, blob_bytes=BLOB_BYTES_MAX, blob_file=BLOB_FILE_MAX,
        want=list(bodies), progs=list(progs), outside=list(outside),
        open=SURVEY_OPEN, close=SURVEY_CLOSE, sec=_SEC_PREFIX, suf=_SEC_SUFFIX)
    prefix = f"cd {_q(cd)} 2>/dev/null; " if cd else ""
    return (f"{SURVEY_CMD_OPEN}\n"
            "__cria_sv_ec=$?\n"
            f"{{ {prefix}python3 - <<'{_HEREDOC}'\n{body}\n{_HEREDOC}\n}} 2>/dev/null\n"
            "( exit $__cria_sv_ec )\n"
            f"{SURVEY_CMD_CLOSE}")


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------- reading it back

# The CLOSE marker is kept in what this returns: `apply_survey` treats its absence as proof the
# result was cut in transit, so stripping it here would hide the one signal that says so.
_BLOCK = re.compile(re.escape(SURVEY_OPEN) + r"\n(.*?\n" + re.escape(SURVEY_CLOSE) + r"|.*)",
                    re.S)


def strip_survey(text: str) -> tuple[str, str]:
    """``(what the model may see, the survey text)``. The survey is cria's own instrumentation
    riding on the model's own call; showing it would be showing the model a command it never
    made — the same contract ``probegate.clean_gate_results`` holds for the gate."""
    if not text or SURVEY_OPEN not in text:
        return text, ""
    found: list[str] = []

    def take(m):
        found.append(m.group(1))
        return ""

    visible = _BLOCK.sub(take, text).replace("\n\n\n", "\n\n")
    return visible.rstrip("\n"), "\n".join(found)


def sections(survey_text: str) -> dict[str, str]:
    """Marker-delimited survey output → ``{section: body}``."""
    out: dict[str, str] = {}
    cur, buf = None, []
    for line in (survey_text or "").splitlines():
        s = line.strip()
        if s.startswith(_SEC_PREFIX) and s.endswith(_SEC_SUFFIX):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = s[len(_SEC_PREFIX):-len(_SEC_SUFFIX)], []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def survey_root(survey_text: str) -> str:
    """The directory the survey actually ran in, as the harness's own shell reported it."""
    for line in (sections(survey_text).get("meta") or "").splitlines():
        key, _, val = line.partition("\t")
        if key == "root":
            return _posix(val.strip())
    return ""


def tree_entries(body: str) -> int:
    """How many records a tree section carries — the count :func:`apply_survey` checks against what
    the survey said it wrote."""
    return sum(1 for ln in (body or "").splitlines() if ln[:2] in ("D\t", "F\t", "X\t"))


# WHY THE LAST SURVEY WAS REFUSED, for the caller that logs it. `apply_survey` answered True/False
# and nothing else, so a walk that found 46 refusals in one session (L5 rust-toml-cli x gemma4) could
# not tell a tree cut in transit from a survey about a different directory — and guessing which is
# how a hypothesis gets written down as a cause (#5b). Four distinct checks refuse; each one names
# itself here and the caller puts it in the event.
_LAST_REJECT: dict = {}


def _note_reject(reason: str, **detail) -> None:
    _LAST_REJECT.clear()
    _LAST_REJECT.update(reason=reason, **{k: str(v)[:200] for k, v in detail.items()})


def last_reject() -> dict:
    """Why the most recent `apply_survey` returned False — `{}` if none has."""
    return dict(_LAST_REJECT)


def apply_survey(view: View, survey_text: str) -> bool:
    """Fold one survey's output into ``view``. False when it carried no tree (a truncated or failed
    run) — then the view keeps whatever it already knew instead of being emptied.

    ALSO FALSE WHEN IT IS ABOUT A DIFFERENT TREE. The survey names the directory it ran in; if that
    is not this view's workspace, folding it in would answer questions about one repo with a listing
    of another. A view with NO root yet adopts the one the survey reports, which is how a session
    whose harness never announced a cwd still gets a workspace."""
    secs = sections(survey_text)
    if "tree" not in secs:
        _note_reject("no-tree-section")
        return False
    # IT MUST HAVE ARRIVED WHOLE. The result this rode home on passes through the harness's own
    # output cap, and a listing cut in transit is indistinguishable from a listing of a smaller
    # repo — every file past the cut would read as deleted, under a heading saying what exists.
    # So the survey states how many records it wrote and closes with a marker; a count that does
    # not match, or a missing close, means what came back is not the answer to anything.
    done = dict(ln.split("\t", 1) for ln in (secs.get("done") or "").splitlines() if "\t" in ln)
    if SURVEY_CLOSE not in survey_text or "entries" not in done:
        _note_reject("cut-in-transit" if SURVEY_CLOSE not in survey_text else "no-entry-count")
        return False
    try:
        if int(done["entries"]) != tree_entries(secs["tree"]):
            _note_reject("entry-count-mismatch",
                         declared=done["entries"], arrived=tree_entries(secs["tree"]))
            return False
    except ValueError:
        _note_reject("entry-count-unparseable")
        return False
    ran_in = survey_root(survey_text)
    if ran_in and view.root and ran_in.rstrip("/") != view.root:
        _note_reject("different-tree", ran_in=ran_in.rstrip("/"), view_root=view.root)
        return False
    if ran_in and not view.root:
        view.root = ran_in.rstrip("/")
    view._survey_generation += 1
    view._ingest_tree(secs["tree"], complete=done.get("complete") != "0")
    if secs.get("blob"):
        view._ingest_blob(secs["blob"])
        # AND SIZE-CHECK WHAT THE BLOB JUST DELIVERED. `_ingest_tree` ends by calling
        # `_drop_stale_bodies`, which compares every remembered body against the size the listing
        # declares — the exact check that catches a body cut in transit. It ran BEFORE the blob was
        # ingested, so the bodies this survey carried were the only ones it never tested.
        #
        # Walked three times in the L5 sub-60 cells. A harness middle-cut inside a base64 body line
        # splices the remains into something `b64decode(validate=False)` still decodes, so cria
        # stored soup and then quoted it as the file: `[binary content: 3,792 bytes]` and
        # "5,734 bytes, 6 lines" for a 7,601-byte, 193-line Importer.java, and
        # `[binary content: 6,225 bytes]` for a test.js the same prompt's inventory called 7,354 B.
        # Both went to a REASONER as ground truth — one authored "the file is binary/corrupted,
        # rewrite it from scratch". A body whose length disagrees with the listing is not a file
        # (#5b); re-running the existing check here drops it and cria re-asks.
        view._drop_stale_bodies()
    if secs.get("outside"):
        view._ingest_outside(secs["outside"])
    if secs.get("progs"):
        view._ingest_progs(secs["progs"])
    return True
