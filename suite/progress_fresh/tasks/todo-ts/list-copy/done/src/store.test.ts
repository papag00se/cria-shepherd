import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});
