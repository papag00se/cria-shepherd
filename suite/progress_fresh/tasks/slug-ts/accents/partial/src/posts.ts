import { slugify } from "./slug";

export interface Post {
  title: string;
  slug: string;
}

export function makePost(title: string): Post {
  return { title, slug: slugify(title) };
}
