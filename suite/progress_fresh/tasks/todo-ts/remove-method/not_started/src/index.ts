import { TodoStore } from "./store";

// usage: node index.js <title>...
const store = new TodoStore();
for (const title of process.argv.slice(2)) store.add(title);
for (const t of store.list()) console.log(`${t.done ? "x" : " "} ${t.id} ${t.title}`);
