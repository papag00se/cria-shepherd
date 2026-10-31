"""Test seams for the compaction predicate.

Compaction fires when one more turn of measured growth no longer fits the room the compaction calls and the
coder request have (``selfcompact.view_room``, computed by ``Loop._compaction_room`` from measured windows).
A test whose subject is NOT that computation — what a fold keeps, what the lenses see — pins the room
directly, the way the old size-trigger tests pinned ``trigger_compaction=100``; the room computation itself
is tested in tests/test_compaction_room.py against real arithmetic."""


def with_room(loop, room: int | None = 100, evidence_room: int | None = None):
    """``loop`` whose room is exactly ``room`` estimated tokens of raw coder view (and ``evidence_room`` tokens
    of compaction evidence); None = unknown window."""
    loop._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (room, evidence_room)
    return loop
