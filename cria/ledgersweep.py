"""The background sweep of the operation ledger (``[retention] ops_idle_after`` / ``ops_sweep_every``; the rule itself is :meth:`cria.ledger.Ledger.sweep`).

cria's bookkeeping of the calls it ran through the harness is one append-only file per session under ``~/.cria/ops``. A session leaves no end signal, so
the files accumulate; by the operator's standing order a ledger whose session has been inactive for ``idle`` seconds (default 30 minutes) is deleted whole,
unless it holds an operation still open or a request for its session is in flight. ``run_once`` never raises; ``start`` runs it once and then every
``every`` seconds on a daemon thread that shares only the ledger's own lock with request handling. One structured event per file removed."""
import threading


class LedgerSweeper:
    def __init__(self, ledger, idle: float, every: float, emit):
        self.ledger, self.idle, self.every, self.emit = ledger, idle, every, emit
        self._stop = threading.Event()
        self._thread = None

    def run_once(self) -> list:
        try:
            removed = self.ledger.sweep(self.idle)
            for entry in removed:
                self.emit('retention.ops_ledger.removed', **entry)
            return removed
        except Exception as exc:  # noqa: BLE001 - a background janitor must never take the service down
            try:
                self.emit('retention.ops_ledger.error', level='error', error=f'{type(exc).__name__}: {exc}')
            except Exception:  # noqa: BLE001 - not even a broken logger may escape
                pass
            return []

    def _loop(self) -> None:
        try:
            self.emit('retention.ops_ledger.enabled', idle_seconds=self.idle, every_seconds=self.every)
        except Exception:  # noqa: BLE001
            pass
        while True:
            self.run_once()
            if self._stop.wait(self.every):
                return

    def start(self) -> 'LedgerSweeper':
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name='cria-ops-ledger-sweep', daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
