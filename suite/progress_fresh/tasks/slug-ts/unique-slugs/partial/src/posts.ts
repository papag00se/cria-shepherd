import { slugify } from "./slug";

export interface Post {
  title: string;
  slug: string;
}

export function makePost(title: string): Post {
  return { title, slug: slugify(title) };
}

export function uniqueSlug(title: string, existing: Set<string>): string {
  const base = slugify(title);
  return existing.has(base) ? base + "-2" : base;
}
