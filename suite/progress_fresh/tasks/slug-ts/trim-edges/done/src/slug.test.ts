import { expect, test } from "vitest";
import { slugify } from "./slug";

test("lowercases and hyphenates", () => {
  expect(slugify("Hello World")).toBe("hello-world");
});

test("trims edge hyphens", () => {
  expect(slugify("  Hello, World!  ")).toBe("hello-world");
});

test("no alphanumerics gives empty string", () => {
  expect(slugify("!!! ???")).toBe("");
});
