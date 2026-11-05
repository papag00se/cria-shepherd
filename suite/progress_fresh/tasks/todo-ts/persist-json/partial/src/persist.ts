import { readFileSync, writeFileSync } from "node:fs";
import { Todo } from "./store";

export function saveTodos(path: string, todos: Todo[]): void {
  writeFileSync(path, JSON.stringify(todos, null, 2));
}

export function loadTodos(path: string): Todo[] {
  return JSON.parse(readFileSync(path, "utf8"));
}
