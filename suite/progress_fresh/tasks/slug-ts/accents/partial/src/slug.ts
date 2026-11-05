export function slugify(title: string): string {
  return title
    .replace(/[éèê]/g, "e")
    .replace(/[àâ]/g, "a")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
}
