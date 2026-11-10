"""The bytes of a file as pieces of the bytes cria read plus the bytes cria wrote, so a batch of edits is sent as splices.

Edits are applied in cria, in call order, to the evolving text; this keeps track of which bytes of the ORIGINAL file are still
there. The result is a list of ``(a, b, new)``: replace ``old[a:b]`` with ``new``, ranges ascending and disjoint - what the harness
``write`` stub applies to the file cria read - so an edit costs the bytes it changes, whatever the file's size (decision D1)."""
import hashlib


class Rope:
    def __init__(self, base: "bytes | None"):
        self.base = base
        self.pieces: list = [("b", 0, len(base))] if base else []      # ("b", start, end) of the base | ("n", bytes) new

    @classmethod
    def whole(cls, data: bytes) -> "Rope":
        rope = cls(None)
        rope.pieces = [("n", data)] if data else []
        return rope

    def tobytes(self) -> bytes:
        return b"".join(self.base[p[1]:p[2]] if p[0] == "b" else p[1] for p in self.pieces)

    def replace(self, a: int, b: int, new: bytes) -> None:
        """Replace the bytes ``[a, b)`` of the text as it reads NOW with ``new``."""
        out, pos, inserted = [], 0, False
        for piece in self.pieces:
            size = piece[2] - piece[1] if piece[0] == "b" else len(piece[1])
            lo, hi = pos, pos + size
            pos = hi
            if hi <= a:                                  # entirely before the span
                out.append(piece)
                continue
            if lo >= b:                                  # entirely after it
                if not inserted:
                    out.append(("n", new))
                    inserted = True
                out.append(piece)
                continue
            if lo < a:                                   # overlaps it: keep what lies outside
                out.append(self._slice(piece, 0, a - lo))
            if not inserted:
                out.append(("n", new))
                inserted = True
            if hi > b:
                out.append(self._slice(piece, b - lo, size))
        if not inserted:
            out.append(("n", new))
        self.pieces = self._merge(out)

    def _slice(self, piece: tuple, x: int, y: int) -> tuple:
        return ("b", piece[1] + x, piece[1] + y) if piece[0] == "b" else ("n", piece[1][x:y])

    @staticmethod
    def _merge(pieces: list) -> list:
        out: list = []
        for p in pieces:
            if (p[0] == "n" and not p[1]) or (p[0] == "b" and p[2] <= p[1]):
                continue
            if out and p[0] == "n" and out[-1][0] == "n":
                out[-1] = ("n", out[-1][1] + p[1])
            elif out and p[0] == "b" and out[-1][0] == "b" and out[-1][2] == p[1]:
                out[-1] = ("b", out[-1][1], p[2])
            else:
                out.append(p)
        return out

    def keeps_base(self) -> bool:
        return any(p[0] == "b" for p in self.pieces)

    def splices(self) -> list:
        """``[(a, b, new)]`` against the original bytes (ascending, disjoint); empty when nothing changed."""
        out, pos, pending = [], 0, b""
        size = len(self.base or b"")
        for piece in self.pieces:
            if piece[0] == "n":
                pending += piece[1]
                continue
            if piece[1] > pos or pending:
                out.append((pos, piece[1], pending))
            pos, pending = piece[2], b""
        if pos < size or pending:
            out.append((pos, size, pending))
        return out


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
