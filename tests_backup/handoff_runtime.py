"""Real session attachment for hardener-origin fixtures (never fabricates an origin)."""
from types import SimpleNamespace

from cria.loop import LoopStore, PlanSession
from cria.plan import Plan, PlanItem


def attach_session(server, key, task):
    store = LoopStore()
    sess = PlanSession(plan=Plan(id=key, task=task, created="fixture",
                                 items=[PlanItem("generated step")]))
    store.put(key, sess)
    server.loop = SimpleNamespace(_store=store)
    return sess
