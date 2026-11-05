import { expect, test } from "vitest";
import { validate } from "./validate";

test("accepts a good form", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 30 })).toEqual([]);
});

test("rejects a short password", () => {
  expect(validate({ email: "a@b.co", password: "x", age: 30 })).toContain("password: too short");
});

test.each(["a@b", "@b.co", "a@@b.co", "plain"])("rejects email %s", (email) => {
  expect(validate({ email, password: "longenough", age: 30 })).toContain("email: invalid");
});
