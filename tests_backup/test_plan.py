import unittest

from cria.plan import Plan, PlanItem


def _plan() -> Plan:
    return Plan(
        id="20260707T004512-3f9a1c2b",
        task="Write a handler: resolve an Ada Handle and return the address",
        created="2026-07-07T00:45:12+00:00",
        items=[
            PlanItem("Confirm the api.handle.me response shape"),
            PlanItem("Write lambda_handler.py using urllib", done=True, note="wrote handler.py"),
            PlanItem("Write unit tests"),
        ],
    )


class PlanFormatTests(unittest.TestCase):
    def test_markdown_roundtrip(self):
        p = _plan()
        back = Plan.from_markdown(p.to_markdown())
        self.assertEqual(back.id, p.id)
        self.assertEqual(back.created, p.created)
        self.assertEqual(back.status, "in_progress")
        self.assertEqual(back.task, p.task)  # a ':' in the task survives (split on first ':')
        self.assertEqual([(i.text, i.done, i.note) for i in back.items],
                         [(i.text, i.done, i.note) for i in p.items])

    def test_checkboxes_render(self):
        md = _plan().to_markdown()
        self.assertIn("- [ ] Confirm the api.handle.me response shape", md)
        self.assertIn("- [x] Write lambda_handler.py using urllib", md)
        self.assertIn("  > wrote handler.py", md)

    def test_current_is_first_undone(self):
        self.assertEqual(_plan().current().text, "Confirm the api.handle.me response shape")
        p = _plan()
        p.items[0].done = True
        self.assertEqual(p.current().text, "Write unit tests")

    def test_remaining(self):
        self.assertEqual(_plan().remaining(), 2)

    def test_none_when_all_done(self):
        p = _plan()
        for it in p.items:
            it.done = True
        self.assertIsNone(p.current())


if __name__ == "__main__":
    unittest.main()
