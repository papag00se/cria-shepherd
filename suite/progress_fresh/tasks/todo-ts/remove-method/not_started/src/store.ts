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
}
