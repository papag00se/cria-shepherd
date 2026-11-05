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
  let slug = base;
  for (let n = 2; existing.has(slug); n++) slug = `${base}-${n}`;
  return slug;
}
