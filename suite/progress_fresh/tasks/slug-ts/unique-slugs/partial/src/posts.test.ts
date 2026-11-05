import { expect, test } from "vitest";
import { uniqueSlug } from "./posts";

test("first collision gets -2", () => {
  expect(uniqueSlug("My Post", new Set(["my-post"]))).toBe("my-post-2");
});
