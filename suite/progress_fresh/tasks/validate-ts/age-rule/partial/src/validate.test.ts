import { expect, test } from "vitest";
import { validate } from "./validate";

test("accepts a good form", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 30 })).toEqual([]);
});

test("rejects a short password", () => {
  expect(validate({ email: "a@b.co", password: "x", age: 30 })).toContain("password: too short");
});

test("rejects a child", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 12 })).toContain("age: out of range");
});
