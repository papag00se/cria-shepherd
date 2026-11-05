import { expect, test } from "vitest";
import { validate } from "./validate";

test("accepts a good form", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 30 })).toEqual([]);
});

test("rejects a short password", () => {
  expect(validate({ email: "a@b.co", password: "x", age: 30 })).toContain("password: too short");
});

test.each([12, 121, 30.5])("rejects age %s", (age) => {
  expect(validate({ email: "a@b.co", password: "longenough", age })).toContain("age: out of range");
});

test.each([13, 120])("accepts boundary age %s", (age) => {
  expect(validate({ email: "a@b.co", password: "longenough", age })).toEqual([]);
});
