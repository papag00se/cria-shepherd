import { expect, test } from "vitest";
import { uniqueSlug } from "./posts";

test("appends increasing suffixes on collision", () => {
  const taken = new Set<string>();
  for (let i = 0; i < 3; i++) taken.add(uniqueSlug("My Post", taken));
  expect([...taken]).toEqual(["my-post", "my-post-2", "my-post-3"]);
});
