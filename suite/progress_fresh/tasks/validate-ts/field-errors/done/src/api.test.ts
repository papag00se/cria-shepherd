import { expect, test } from "vitest";
import { signup } from "./api";

test("groups errors by field", () => {
  const r = signup({ email: "nope", password: "x", age: 30 });
  expect(r.ok).toBe(false);
  expect(Object.keys(r.errors).sort()).toEqual(["email", "password"]);
});

test("ok has no errors", () => {
  expect(signup({ email: "a@b.co", password: "longenough", age: 30 })).toEqual({ ok: true, errors: {} });
});
