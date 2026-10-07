#!/usr/bin/env python3
"""Resumable, planner-off fresh L5 campaign manifest (never edits historical rows)."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
try:
    from .run import collect_capture
except ImportError:
    from run import collect_capture

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
MANIFEST = SUITE / "results" / "fresh-l5-manifest.json"
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5", "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill", "nemotron-elastic")
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py", "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
LEVEL = 5


def rows():
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text(errors="replace").splitlines():
        try: out.append(json.loads(line))
        except ValueError: continue
    return out


def _valid_response(response: object) -> bool:
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    return (isinstance(choices, list) and bool(choices)
            and isinstance(choices[0], dict)
            and isinstance(choices[0].get("message"), dict))


def _capture_dirs(row: dict) -> list[Path]:
    dirs = row.get("capture_dirs")
    if not isinstance(dirs, list) or not dirs:
        one = row.get("capture_dir")
        dirs = [one] if isinstance(one, str) and one else []
    return [Path(d) for d in dirs if isinstance(d, str) and d]


def _valid_capture_evidence(row: dict) -> bool:
    """Verify shutdown evidence; pending requests' later responses stay uncredited."""
    if "capture_snapshot" in row and not isinstance(row["capture_snapshot"], dict):
        return False
    snapshot = row.get("capture_snapshot")
    if isinstance(snapshot, dict):
        entries = snapshot.get("entries")
        if snapshot.get("complete") is not True or not isinstance(entries, list) or not entries:
            return False
        completed = []
        named_requests = set()
        for entry in entries:
            if not isinstance(entry, dict):
                return False
            request = Path(str(entry.get("request", "")))
            match = re.match(r"^(\d+)-(.+)\.json$", request.name)
            phase = entry.get("phase")
            if (not request.is_file() or request in named_requests or not match
                    or type(entry.get("seq")) is not int or int(match.group(1)) != entry["seq"]
                    or not isinstance(phase, str) or match.group(2) != phase):
                return False
            named_requests.add(request)
            try:
                if hashlib.sha256(request.read_bytes()).hexdigest() != entry.get("sha256"):
                    return False
                req = json.loads(request.read_text())
                response = request.with_name(request.stem + ".response.json")
                if (req.get("phase") != phase
                        or not isinstance(req.get("body"), dict)
                        or not isinstance(req["body"].get("messages"), list)
                        or not isinstance(entry.get("phase"), str)):
                    return False
                if entry.get("response"):
                    if entry.get("pending") is True or Path(entry["response"]) != response or not response.is_file():
                        return False
                    if hashlib.sha256(response.read_bytes()).hexdigest() != entry.get("response_sha256"):
                        return False
                    response_obj = json.loads(response.read_text())
                    if not _valid_response(response_obj):
                        return False
                    completed.append((phase, response, response_obj))
                elif entry.get("pending") is not True:
                    return False
                elif response.exists():
                    response_obj = json.loads(response.read_text())  # late response is retained, not counted
                    if not _valid_response(response_obj):
                        return False
            except (OSError, ValueError, TypeError):
                return False
        dirs = _capture_dirs(row)
        if not dirs or not all(directory.is_dir() for directory in dirs):
            return False
        actual_requests = {p for directory in dirs
                           for p in directory.glob("[0-9]*-*.json")
                           if re.match(r"^\d+-.+\.json$", p.name)
                           and not p.name.endswith((".response.json", ".prompt.txt", ".reasoning.txt"))}
        expected_responses = {Path(entry["response"]) for entry in entries if entry.get("response")}
        expected_responses.update(
            request.with_name(request.stem + ".response.json")
            for entry in entries if entry.get("pending")
            for request in [Path(entry["request"])]
            if request.with_name(request.stem + ".response.json").is_file())
        actual_responses = {p for directory in dirs for p in directory.glob("*.response.json")}
        # A stopped harness can leave one already-issued completion in flight and that completion
        # can immediately issue one follow-up request before shutdown reaches the proxy. Preserve
        # these artifacts, but never add them to the measured snapshot. The exception is precisely
        # bounded: one pending request from the snapshot may complete late, and one subsequent
        # request/response pair may be recorded, in the same non-planner phase and strictly after
        # the run cutoff. No further request can be laundered through this allowance.
        extras = actual_requests - named_requests
        cutoff = float(row.get("started", 0)) + float(row.get("wall_seconds", 0))
        late_entries = [entry for entry in entries if entry.get("pending") and
                        Path(entry["request"]).with_name(Path(entry["request"]).stem + ".response.json") in actual_responses]
        bounded_followup = False
        if len(extras) == 1 and len(late_entries) == 1 and len(actual_responses - expected_responses) == 1:
            followup, = extras
            match = re.match(r"^(\d+)-(.+)\.json$", followup.name)
            previous = Path(late_entries[0]["request"])
            previous_response = previous.with_name(previous.stem + ".response.json")
            followup_response = followup.with_name(followup.stem + ".response.json")
            try:
                data = json.loads(followup.read_text())
                answer = json.loads(followup_response.read_text())
                bounded_followup = (match is not None and int(match.group(1)) == int(late_entries[0]["seq"]) + 1
                    and data.get("seq") == int(match.group(1))
                    and isinstance(data.get("phase"), str) and not data["phase"].startswith("planner")
                    and isinstance(data.get("body"), dict) and isinstance(data["body"].get("messages"), list)
                    and previous.stat().st_mtime <= cutoff < previous_response.stat().st_mtime
                    and previous_response.stat().st_mtime <= followup.stat().st_mtime
                    and followup_response in actual_responses - expected_responses
                    and _valid_response(answer)
                    and followup_response.stat().st_mtime >= followup.stat().st_mtime)
            except (OSError, ValueError, TypeError):
                bounded_followup = False
        if (not (actual_requests == named_requests or bounded_followup)
                or actual_responses - expected_responses != ({Path(next(iter(extras)).with_name(next(iter(extras)).stem + ".response.json"))} if bounded_followup else set())
                or any(str(entry.get("phase", "")).startswith("planner") for entry in entries)):
            return False
        phases = {}
        for _phase, response, _response_obj in completed:
            match = re.match(r"\d+-(.+?)(?:-s\d+.*)?\.response\.json$", response.name)
            key = match.group(1) if match else "unknown"
            phases[key] = phases.get(key, 0) + 1
        return len(completed) == row.get("calls") and phases == row.get("phases")
    dirs = row.get("capture_dirs")
    if not isinstance(dirs, list) or not dirs:
        one = row.get("capture_dir")
        dirs = [one] if isinstance(one, str) and one else []
    if not all(isinstance(d, str) and d for d in dirs):
        return False
    responses = [p for d in dirs for p in Path(d).glob("*.response.json")]
    if not responses:
        return False
    try:
        cutoff = float(row["started"]) + float(row["wall_seconds"])
        late_responses = [path for path in responses if path.stat().st_mtime > cutoff]
    except (KeyError, OSError, TypeError, ValueError):
        return False
    if late_responses:
        return _valid_post_stop_response(row, dirs, responses)
    if row.get("calls") != len(responses):
        return False
    for response in responses:
        name = response.name
        request = response.with_name(name.removesuffix(".response.json") + ".json")
        try:
            req = json.loads(request.read_text())
            res = json.loads(response.read_text())
        except (OSError, ValueError):
            return False
        choices = res.get("choices") if isinstance(res, dict) else None
        filename_phase = name.split("-", 1)[1].removesuffix(".response.json") if "-" in name else ""
        body = req.get("body") if isinstance(req, dict) else None
        if (not isinstance(req, dict) or not filename_phase
                or req.get("phase") != filename_phase
                or not isinstance(body, dict) or not isinstance(body.get("messages"), list)
                or not _valid_response(res)):
            return False
    captured = collect_capture([Path(d) for d in dirs])
    return captured.get("calls") == row.get("calls") and captured.get("phases") == row.get("phases")


def _valid_post_stop_response(row: dict, dirs: list[str], responses: list[Path]) -> bool:
    """A single response may finish after shutdown for a request already captured before it.

    It remains preserved but outside the row's measured call inventory. Require the archived
    workspace snapshot to predate that response and every late file-edit target to be unchanged
    since the row ended; all in-window calls must still exactly match the row's counts/phases.
    """
    try:
        cutoff = float(row["started"]) + float(row["wall_seconds"])
        late = [path for path in responses if path.stat().st_mtime > cutoff]
        if len(late) != 1:
            return False
        late_response = late[0]
        late_request = late_response.with_name(late_response.name.removesuffix(".response.json") + ".json")
        request_data = json.loads(late_request.read_text())
        response_data = json.loads(late_response.read_text())
        phase = request_data.get("phase")
        if (not isinstance(phase, str) or phase.startswith("planner")
                or late_request.stat().st_mtime > cutoff
                or not isinstance(request_data.get("body"), dict)
                or not isinstance(request_data["body"].get("messages"), list)):
            return False
        choices = response_data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if not isinstance(tool_calls, list) or not tool_calls:
            return False
        archive_workspace = Path(row["archive"]) / "workspace"
        if not archive_workspace.is_dir() or archive_workspace.stat().st_mtime > late_response.stat().st_mtime:
            return False
        for call in tool_calls:
            function = call.get("function", {})
            if function.get("name") not in {"edit_file", "write_file"}:
                return False
            args = json.loads(function.get("arguments", "{}"))
            target = (archive_workspace / args["path"]).resolve()
            if archive_workspace.resolve() not in target.parents and target != archive_workspace.resolve():
                return False
            if not target.is_file() or target.stat().st_mtime > late_response.stat().st_mtime:
                return False
        on_time = [path for path in responses if path != late_response]
        if any(path.stat().st_mtime > cutoff for path in on_time):
            return False
        dirs_paths = [Path(directory) for directory in dirs]
        requests = {path for directory in dirs_paths for path in directory.glob("[0-9]*-*.json")
                    if re.match(r"^\d+-.+\.json$", path.name)
                    and not path.name.endswith((".response.json", ".prompt.txt", ".reasoning.txt"))}
        if requests != {path.with_name(path.name.removesuffix(".response.json") + ".json")
                        for path in responses}:
            return False
        if any(request.stat().st_mtime > cutoff for request in requests):
            return False
        for response in responses:
            request = response.with_name(response.name.removesuffix(".response.json") + ".json")
            req = json.loads(request.read_text())
            res = json.loads(response.read_text())
            phase_match = re.match(r"\d+-(.+?)(?:-s\d+.*)?\.response\.json$", response.name)
            choices = res.get("choices") if isinstance(res, dict) else None
            filename_phase = response.name.split("-", 1)[1].removesuffix(".response.json")
            if (not phase_match or req.get("phase") != filename_phase
                    or str(req.get("phase", "")).startswith("planner")
                    or not isinstance(req.get("body"), dict)
                    or not isinstance(req["body"].get("messages"), list)
                    or not _valid_response(res)):
                return False
        captured = collect_capture_for_responses(on_time)
        return captured.get("calls") == row.get("calls") and captured.get("phases") == row.get("phases")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def collect_capture_for_responses(responses: list[Path]) -> dict:
    phases = {}
    for response in responses:
        match = re.match(r"\d+-(.+?)(?:-s\d+.*)?\.response\.json$", response.name)
        if not match:
            return {"calls": -1, "phases": {}}
        phase = match.group(1)
        phases[phase] = phases.get(phase, 0) + 1
    return {"calls": len(responses), "phases": phases}


def _valid_live_settings(row: dict) -> bool:
    try:
        from .sampling import render
    except ImportError:
        from sampling import render
    code_revision = row.get("code_revision")
    return (row.get("sampling") == render(row.get("model", ""))
            and (code_revision is None or
                 isinstance(code_revision, str) and re.fullmatch(r"[0-9a-f]{40}", code_revision)))


def _eligible(row: dict, revision: str) -> bool:
    archive = Path(row.get("archive") or "")
    return (
        type(row.get("level")) is int and row["level"] == LEVEL
        and type(row.get("live_engagement_level")) is int and row["live_engagement_level"] == LEVEL
        and not row.get("superseded") and not row.get("aborted")
        and row.get("terminal") not in (None, "crashed-early", "harness-error")
        and row.get("workspace_lost") is False
        and (archive / "workspace").is_dir()
        and row.get("planner") == "off" and row.get("planner_enabled") is False
        and row.get("planner_phase_count") == 0
        and isinstance(row.get("phases"), dict) and row["phases"].get("planner", 0) == 0
        and str(row.get("note", "")).startswith("FRESH-L5 ")
        and row.get("revision") == revision
        and _valid_live_settings(row)
        and _valid_capture_evidence(row)
    )


def worklist(revision: str, result_rows=None):
    """Fresh cells only; requested settings never substitute for captured run evidence."""
    if not revision or any(c.isspace() for c in revision):
        raise ValueError("a fixed git revision is required")
    done = set()
    for row in result_rows if result_rows is not None else rows():
        if _eligible(row, revision):
            done.add((row.get("model"), row.get("task")))
    return [{"model": m, "task": t, "level": LEVEL, "revision": revision, "planner": "off"}
            for m in MODELS for t in TASKS if (m, t) not in done]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--revision", required=True, help="immutable cria git revision for every cell")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()
    try:
        from .campaign_provenance import validate
    except ImportError:
        from campaign_provenance import validate
    code_revision = validate(args.revision)
    cells = worklist(args.revision)
    payload = {"schema": 1, "level": LEVEL, "revision": args.revision,
               "code_revision": code_revision, "planner": "off",
               "expected_cells": len(MODELS) * len(TASKS), "remaining": cells}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, indent=2) + "\n")
    for cell in cells:
        print(f"{cell['model']}\t{cell['task']}\tL5\t{cell['revision']}\tplanner=off")
    print(f"manifest={args.manifest} remaining={len(cells)}")

if __name__ == "__main__": main()
