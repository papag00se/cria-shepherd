import { expect, test } from "vitest";
import { slugify } from "./slug";

test("lowercases and hyphenates", () => {
  expect(slugify("Hello World")).toBe("hello-world");
});

test("folds accents", () => {
  expect(slugify("Crème Brûlée")).toBe("creme-brulee");
});
