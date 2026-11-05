import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});

test("remove deletes", () => {
  const s = new TodoStore();
  const t = s.add("a");
  expect(s.remove(t.id)).toBe(true);
  expect(s.list()).toHaveLength(0);
});
