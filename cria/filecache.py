"""The bytes cria has read from the harness this process, so a repeated read costs a stat and a hash, not the file.

Entries are keyed by the path cria read, hold the sha-256 and size of the whole file as the harness reported them, and the
longest prefix of the file cria holds (all of it, or the part a window needed). Nothing is served without the harness's own
fresh sha-256 and size of the file: a stale entry costs one round trip, never a wrong answer (docs/harness-primitives.md 8.1).
Bounded: 16 MiB of bytes, least recently used first."""
import threading
from collections import OrderedDict

CAP_BYTES = 16 << 20


class FileCache:
    def __init__(self, cap: int = CAP_BYTES):
        self.cap = cap
        self._lock = threading.Lock()
        self._items: OrderedDict = OrderedDict()
        self._held = 0

    def get(self, root: str, rel: str):
        """The entry for a path (``(sha, size, bytes)``), or None."""
        with self._lock:
            item = self._items.get((root, rel))
            if item is not None:
                self._items.move_to_end((root, rel))
            return item

    def prefix(self, root: str, rel: str, sha: str, size: int) -> bytes:
        """The held bytes of the file whose identity is ``(sha, size)``, from offset 0; empty when the entry is another file's."""
        item = self.get(root, rel)
        return item[2] if item is not None and item[:2] == (sha, size) else b''

    def put(self, root: str, rel: str, sha: str, size: int, data: bytes) -> None:
        if len(data) > self.cap:
            return
        with self._lock:
            old = self._items.pop((root, rel), None)
            if old is not None:
                self._held -= len(old[2])
            self._items[(root, rel)] = (sha, size, data)
            self._held += len(data)
            while self._held > self.cap and self._items:
                _, (_s, _z, dropped) = self._items.popitem(last=False)
                self._held -= len(dropped)
