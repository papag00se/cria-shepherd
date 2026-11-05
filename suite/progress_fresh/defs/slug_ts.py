from suite.progress_fresh.dsl import ed

SEED = {
"src/slug.ts": '''export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
}
''',
"src/slug.test.ts": '''import { expect, test } from "vitest";
import { slugify } from "./slug";

test("lowercases and hyphenates", () => {
  expect(slugify("Hello World")).toBe("hello-world");
});
''',
"src/posts.ts": '''import { slugify } from "./slug";

export interface Post {
  title: string;
  slug: string;
}

export function makePost(title: string): Post {
  return { title, slug: slugify(title) };
}
''',
}
S = SEED["src/slug.ts"]
T = SEED["src/slug.test.ts"]
P = SEED["src/posts.ts"]
TASK = dict(extension=True, name="slug-ts", language="TypeScript", seed=SEED,
unrelated={"src/posts.ts": "// posts are identified by their slug\n" + P},
reqs=[
dict(id="trim-edges", text="slugify(\"  Hello, World!  \") currently yields \"-hello-world-\". Strip leading and trailing hyphens, and make sure an input with no alphanumerics returns an empty string; test both.",
 partial={"src/slug.ts": ed(S, ('.replace(/[^a-z0-9]+/g, "-");', '.replace(/[^a-z0-9]+/g, "-")\n    .replace(/^-/, "");'))},
 done={"src/slug.ts": ed(S, ('.replace(/[^a-z0-9]+/g, "-");', '.replace(/[^a-z0-9]+/g, "-")\n    .replace(/^-+|-+$/g, "");')),
       "src/slug.test.ts": T + '''
test("trims edge hyphens", () => {
  expect(slugify("  Hello, World!  ")).toBe("hello-world");
});

test("no alphanumerics gives empty string", () => {
  expect(slugify("!!! ???")).toBe("");
});
'''}),
dict(id="accents", text="Fold accented Latin letters to ASCII before slugifying (\"Crème Brûlée\" -> \"creme-brulee\") using Unicode normalization.",
 partial={"src/slug.ts": ed(S, ("    .toLowerCase()", "    .replace(/[éèê]/g, \"e\")\n    .replace(/[àâ]/g, \"a\")\n    .toLowerCase()")),
          "src/slug.test.ts": T + '''
test("folds accents", () => {
  expect(slugify("Crème")).toBe("creme");
});
'''},
 done={"src/slug.ts": ed(S, ("    .toLowerCase()", "    .normalize(\"NFD\")\n    .replace(/[\\u0300-\\u036f]/g, \"\")\n    .toLowerCase()")),
       "src/slug.test.ts": T + '''
test("folds accents", () => {
  expect(slugify("Crème Brûlée")).toBe("creme-brulee");
});
'''}),
dict(id="unique-slugs", text="makePost must produce unique slugs within a list: add uniqueSlug(title, existing: Set<string>) in posts.ts that appends -2, -3, ... when the slug is taken, and test the collision sequence.",
 partial={"src/posts.ts": P + '''
export function uniqueSlug(title: string, existing: Set<string>): string {
  const base = slugify(title);
  return existing.has(base) ? base + "-2" : base;
}
'''},
 done={"src/posts.ts": P + '''
export function uniqueSlug(title: string, existing: Set<string>): string {
  const base = slugify(title);
  let slug = base;
  for (let n = 2; existing.has(slug); n++) slug = `${base}-${n}`;
  return slug;
}
''', "src/posts.test.ts": '''import { expect, test } from "vitest";
import { uniqueSlug } from "./posts";

test("appends increasing suffixes on collision", () => {
  const taken = new Set<string>();
  for (let i = 0; i < 3; i++) taken.add(uniqueSlug("My Post", taken));
  expect([...taken]).toEqual(["my-post", "my-post-2", "my-post-3"]);
});
'''}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["trim-edges"]["src/slug.test.ts"] = T + '''
test("trims a leading hyphen", () => {
  expect(slugify("  Hello World")).toBe("hello-world");
});
'''
_P["unique-slugs"]["src/posts.test.ts"] = '''import { expect, test } from "vitest";
import { uniqueSlug } from "./posts";

test("first collision gets -2", () => {
  expect(uniqueSlug("My Post", new Set(["my-post"]))).toBe("my-post-2");
});
'''
