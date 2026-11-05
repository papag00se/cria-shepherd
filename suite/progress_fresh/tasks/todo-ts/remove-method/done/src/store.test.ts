import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});

test("remove deletes an existing todo", () => {
  const s = new TodoStore();
  const t = s.add("a");
  s.add("b");
  expect(s.remove(t.id)).toBe(true);
  expect(s.list().map((x) => x.title)).toEqual(["b"]);
});

test("remove of an unknown id returns false and keeps everything", () => {
  const s = new TodoStore();
  s.add("a");
  expect(s.remove(99)).toBe(false);
  expect(s.list()).toHaveLength(1);
});
