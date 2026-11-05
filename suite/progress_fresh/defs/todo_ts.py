TASK = dict(name="todo-ts", language="TypeScript", seed={
"package.json": '{\n  "name": "todo-store",\n  "version": "0.1.0",\n  "scripts": {"test": "vitest run"},\n  "devDependencies": {"typescript": "^5.4.0", "vitest": "^1.6.0"}\n}\n',
"src/store.ts": '''export interface Todo {
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
}
''',
"src/index.ts": '''import { TodoStore } from "./store";

const store = new TodoStore();
for (const title of process.argv.slice(2)) store.add(title);
for (const t of store.list()) console.log(`${t.done ? "x" : " "} ${t.id} ${t.title}`);
''',
"src/store.test.ts": '''import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});
''',
}, unrelated={"src/index.ts": '''import { TodoStore } from "./store";

// usage: node index.js <title>...
const store = new TodoStore();
for (const title of process.argv.slice(2)) store.add(title);
for (const t of store.list()) console.log(`${t.done ? "x" : " "} ${t.id} ${t.title}`);
'''},
reqs=[
dict(id="list-copy", text="list() currently hands out the internal array, so callers can mutate the store. Return a defensive copy and make sure callers cannot change stored todos through the returned objects either.",
 partial={"src/store.ts": '''export interface Todo {
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
    return [...this.items];
  }
}
'''},
 done={"src/store.ts": '''export interface Todo {
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
    return { ...todo };
  }

  complete(id: number): void {
    const t = this.items.find((i) => i.id === id);
    if (t) t.done = true;
  }

  list(): Todo[] {
    return this.items.map((t) => ({ ...t }));
  }
}
'''}),
dict(id="remove-method", text="Add a remove(id) method to TodoStore that deletes a todo and returns true, or returns false (changing nothing) when the id does not exist; cover both outcomes with tests in src/store.test.ts.",
 partial={"src/store.ts": '''export interface Todo {
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

  remove(id: number): boolean {
    const idx = this.items.findIndex((i) => i.id === id);
    this.items.splice(idx, 1);
    return true;
  }

  list(): Todo[] {
    return this.items;
  }
}
''', "src/store.test.ts": '''import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});

test("remove deletes", () => {
  const s = new TodoStore();
  const t = s.add("a");
  expect(s.remove(t.id)).toBe(true);
  expect(s.list()).toHaveLength(0);
});
'''},
 done={"src/store.ts": '''export interface Todo {
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

  remove(id: number): boolean {
    const idx = this.items.findIndex((i) => i.id === id);
    if (idx < 0) return false;
    this.items.splice(idx, 1);
    return true;
  }

  list(): Todo[] {
    return this.items;
  }
}
''', "src/store.test.ts": '''import { expect, test } from "vitest";
import { TodoStore } from "./store";

test("add assigns increasing ids", () => {
  const s = new TodoStore();
  expect(s.add("a").id).toBe(1);
  expect(s.add("b").id).toBe(2);
});

test("remove deletes an existing todo", () => {
  const s = new TodoStore();
  const t = s.add("a");
  s.add("b");
  expect(s.remove(t.id)).toBe(true);
  expect(s.list().map((x) => x.title)).toEqual(["b"]);
});

test("remove of an unknown id returns false and keeps everything", () => {
  const s = new TodoStore();
  s.add("a");
  expect(s.remove(99)).toBe(false);
  expect(s.list()).toHaveLength(1);
});
'''}),
dict(id="persist-json", text="Add persistence: TodoStore gets save(path) and a static load(path) that round-trip the todos (including done flags and the next id) through a JSON file, and index.ts loads from and saves to todos.json in the working directory.",
 partial={"src/persist.ts": '''import { readFileSync, writeFileSync } from "node:fs";
import { Todo } from "./store";

export function saveTodos(path: string, todos: Todo[]): void {
  writeFileSync(path, JSON.stringify(todos, null, 2));
}

export function loadTodos(path: string): Todo[] {
  return JSON.parse(readFileSync(path, "utf8"));
}
'''},
 done={"src/store.ts": '''import { readFileSync, writeFileSync } from "node:fs";

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
''', "src/index.ts": '''import { TodoStore } from "./store";

const FILE = "todos.json";
const store = TodoStore.load(FILE);
for (const title of process.argv.slice(2)) store.add(title);
for (const t of store.list()) console.log(`${t.done ? "x" : " "} ${t.id} ${t.title}`);
store.save(FILE);
'''}),
])
