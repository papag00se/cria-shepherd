"""Five rewrites of one file are a wheel only while the repo's checks keep naming the same fault.

Rust cell 2 (`rust-toml-cli`, 2026-11-01): write_file + three edit_file calls to src/main.rs, each fixing the error
the last `cargo test` named (E0573/E0277, then E0308/E0599), tripped the wheel-spin guard on the fifth write; the
reasoner then authored a half-applied action over a converging sequence. The same guard must still fire on a real
wheel: cart.go in 01a0454d, where `go test` printed the identical "no required module provides package" after
every rewrite.
"""
import json

import pytest
from cria import checkmotion, loop, stalledwork as sw
from loop_orientation_helpers import Log  # noqa: F401

# Verbatim tool results (Codex exec envelope) of the two `cargo test --quiet 2>&1 | tail` runs in that cell.
CARGO_1 = """Chunk ID: e45f90
Wall time: 0.0000 seconds
Process exited with code 0
Original token count: 411
Output:
error[E0573]: expected type, found function `std::env::args_os`
  --> src/main.rs:46:14
   |
46 | fn run(args: std::env::args_os()) -> ExitCode {
   |              ^^^^^^^^^^^^^^^^^^^ not a type

error[E0277]: a value of type `Result<Vec<std::string::String>, std::string::String>` cannot be built from an iterator over elements of type `std::string::String`
  --> src/main.rs:18:10
   |
18 |         .collect()
   |          ^^^^^^^ value of type `Result<Vec<std::string::String>, std::string::String>` cannot be built from `std::iter::Iterator<Item=std::string::String>`

Some errors have detailed explanations: E0277, E0573.
For more information about an error, try `rustc --explain E0277`.
error: could not compile `toml-get` (bin "toml-get" test) due to 2 previous errors
"""
CARGO_2 = """Chunk ID: 6ab7f6
Wall time: 0.0000 seconds
Process exited with code 0
Original token count: 276
Output:
error[E0308]: mismatched types
  --> src/main.rs:95:9
   |
95 |     run(std::env::args_os())
   |     --- ^^^^^^^^^^^^^^^^^^^ expected `Vec<String>`, found `ArgsOs`
   |     |
   |     arguments to this function are incorrect

error[E0599]: no method named `unwrap` found for struct `Vec<std::string::String>` in the current scope
   --> src/main.rs:146:54
    |
146 |         let segments = parse_key_path("server.port").unwrap();
    |                                                      ^^^^^^

Some errors have detailed explanations: E0308, E0599.
error: could not compile `toml-get` (bin "toml-get" test) due to 4 previous errors
"""
CARGO_3 = CARGO_2.replace("95", "96").replace("146", "150")      # the same two faults, the lines moved
GO = """Chunk ID: 4c56d7
Wall time: 0.0000 seconds
Process exited with code 1
Original token count: 37
Output:
cart.go:10:2: no required module provides package github.com/shopspring/decimal/rounding; to add it:
	go get github.com/shopspring/decimal/rounding
"""
PYTHON = "Output:\nFAILED tests/test_a.py::test_x - assert {n} == 8\n1 failed in 0.1s\n"


def run(cmd, output):
    return ("exec_command", {"cmd": cmd}, output)


def write(path="src/main.rs"):
    return ("edit_file", {"path": path, "old_string": "a", "new_string": "b"}, "Wrote " + path)


def history(*steps):
    """Messages the harness would send before the LAST step's reply, as the live loop sees them."""
    msgs = [{"role": "user", "content": "do it"}]
    for n, (name, args, output) in enumerate(steps):
        msgs += [{"role": "assistant", "tool_calls": [{"id": f"c{n}", "type": "function", "function": {
                      "name": name, "arguments": json.dumps(args)}}]},
                 {"role": "tool", "tool_call_id": f"c{n}", "content": output}]
    return msgs


def replay(*steps):
    """Forward every step's reply through the real tracker, each with the history that preceded it."""
    gs, log = loop.GuardState(), Log()
    msgs = history(*steps)
    for n, (name, args, _output) in enumerate(steps):
        if name == "edit_file":
            reply = {"choices": [{"message": {"tool_calls": [{"id": f"c{n}", "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}]}}]}
            loop.guard_track_write_streak(gs, reply, log, messages=msgs[:2 * n + 1])
    return gs, log


def test_the_real_rust_sequence_each_edit_fixing_a_new_error_is_progress_not_a_wheel():
    tool = "cargo test --quiet 2>&1 | tail -40"
    gs, log = replay(write(), run(tool, CARGO_1), write(), write(), write(), run(tool, CARGO_2), write())
    assert not gs.spin_probe_due and "loop.wheel_spinning" not in log.kinds()
    assert "loop.wheel_spin_progress" in log.kinds() and gs.recent_writes == []     # the window restarts


def test_the_real_go_wheel_the_same_error_after_every_rewrite_still_trips():
    tool = "go test -count=1 -v ./..."
    gs, log = replay(write("cart.go"), run(tool, GO), write("cart.go"), run(tool, GO), write("cart.go"),
                     run(tool, GO), write("cart.go"), write("cart.go"))
    assert gs.spin_probe_due and gs.spin_path == "cart.go" and "loop.wheel_spin_progress" not in log.kinds()


@pytest.mark.parametrize("runs,moving", [
    ([CARGO_1, CARGO_2], True),                      # every earlier error fixed, new ones named
    ([CARGO_1, CARGO_2, CARGO_3], True),             # the same E0308/E0599 with moved lines is one fault, not a new one
    ([GO, GO, GO], False),                           # a wheel: nothing was fixed
    ([CARGO_1, CARGO_2, CARGO_1], False),            # an error that comes back is not progress
    ([PYTHON.format(n=n) for n in (7, 9, 11)], False),    # a constant the coder keeps changing is the same fault
    ([CARGO_2, CARGO_1 + CARGO_2], False),           # errors only added
    ([CARGO_1], False),                              # one run proves nothing
    ([CARGO_1, "Process running with session ID 7\nOutput:\n"], False),   # a run that printed nothing parseable says nothing
])
def test_motion_needs_an_error_that_was_reported_then_gone_and_never_back(runs, moving):
    cmd = "go test ./..." if runs[0] is GO else "cargo test" if "error[" in runs[0] else "python -m pytest -q"
    assert checkmotion.moving(checkmotion.outputs((cmd, text) for text in runs)) is moving


def test_only_check_commands_count_so_a_cat_of_compiler_output_is_not_a_run():
    assert checkmotion.outputs([("cat build.log", CARGO_1), ("cargo test", CARGO_2)]) == checkmotion.outputs([("cargo test", CARGO_2)])
    assert checkmotion.error_identities("cat build.log", CARGO_1) == frozenset()


def test_without_the_reader_or_a_readable_first_write_the_guard_trips_as_before():
    """Fail toward the old behaviour: no reader, or a first window write the messages no longer hold (compaction)."""
    for reader in (None, lambda _id: ()):
        state = sw.State(recent_writes=["x"] * 4, recent_write_ids=list("abcd"))
        facts = sw.ObservationFacts((sw.ForwardedCall("e", "x"),), 0, "", check_outputs=reader)
        assert sw.observe(sw.ObservationInput(lambda: facts, Log()), state).trigger is sw.Trigger.WHEEL_SPIN
