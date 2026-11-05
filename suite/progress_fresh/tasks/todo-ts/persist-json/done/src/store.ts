import { readFileSync, writeFileSync } from "node:fs";

export interface Todo {
  id: number;
  title: string;
  done: boolean;
}

export class TodoStore {
  private items: Todo[] = [];
  private nextId = 1;

  add(title: string): Todo {
    const todo = { id: this.nextId++, title, done: false };
    this.items.push(todo);
    return todo;
  }

  complete(id: number): void {
    const t = this.items.find((i) => i.id === id);
    if (t) t.done = true;
  }

  list(): Todo[] {
    return this.items;
  }

  save(path: string): void {
    writeFileSync(path, JSON.stringify({ nextId: this.nextId, items: this.items }));
  }

  static load(path: string): TodoStore {
    const s = new TodoStore();
    try {
      const raw = JSON.parse(readFileSync(path, "utf8"));
      s.items = raw.items;
      s.nextId = raw.nextId;
    } catch (e: any) {
      if (e.code !== "ENOENT") throw e;
    }
    return s;
  }
}
