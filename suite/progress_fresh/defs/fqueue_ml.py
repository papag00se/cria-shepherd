from suite.progress_fresh.dsl import ed

SEED = {
"lib/fqueue.ml": '''type 'a t = { front : 'a list; back : 'a list }

let empty = { front = []; back = [] }

let push x q = { q with back = x :: q.back }

let pop q =
  match q.front with
  | x :: rest -> Some (x, { q with front = rest })
  | [] -> None
''',
"lib/fqueue.mli": '''type 'a t

val empty : 'a t
val push : 'a -> 'a t -> 'a t
val pop : 'a t -> ('a * 'a t) option
''',
"test/test_fqueue.ml": '''let () =
  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in
  match Fqueue.pop q with
  | Some (_, _) -> print_endline "popped"
  | None -> print_endline "empty"
''',
}
M = SEED["lib/fqueue.ml"]
I = SEED["lib/fqueue.mli"]
T = SEED["test/test_fqueue.ml"]
POP_NEW = '''let pop q =
  match q.front with
  | x :: rest -> Some (x, { q with front = rest })
  | [] -> (
      match List.rev q.back with
      | [] -> None
      | x :: rest -> Some (x, { front = rest; back = [] }))
'''
TASK = dict(extension=True, name="fqueue-ml", language="OCaml", seed=SEED,
unrelated={"lib/fqueue.mli": "(* functional FIFO queue *)\n" + I},
reqs=[
dict(id="fifo-fix", text="pop never looks at the back list, so items pushed onto an empty queue are never returned. Fix pop to move the back list over (reversed) when the front is empty, so elements come out in FIFO order.",
 partial={"lib/fqueue.ml": ed(M, ("  | [] -> None\n", "  | [] -> (\n      match List.rev q.back with\n      | [] -> None\n      | x :: rest -> Some (x, { front = rest; back = q.back }))\n"))},
 done={"lib/fqueue.ml": ed(M, ("let pop q =\n  match q.front with\n  | x :: rest -> Some (x, { q with front = rest })\n  | [] -> None\n", POP_NEW))}),
dict(id="length-peek", text="Add length : 'a t -> int and peek : 'a t -> 'a option (does not remove), expose both in fqueue.mli, and test them.",
 partial={"lib/fqueue.ml": M + "\nlet length q = List.length q.front + List.length q.back\n\nlet peek q = match q.front with x :: _ -> Some x | [] -> None\n",
          "lib/fqueue.mli": I + "val length : 'a t -> int\nval peek : 'a t -> 'a option\n"},
 done={"lib/fqueue.ml": ed(M, ("let pop q =\n  match q.front with\n  | x :: rest -> Some (x, { q with front = rest })\n  | [] -> None\n", POP_NEW)) + "\nlet length q = List.length q.front + List.length q.back\n\nlet peek q =\n  match q.front with\n  | x :: _ -> Some x\n  | [] -> ( match List.rev q.back with x :: _ -> Some x | [] -> None)\n",
       "lib/fqueue.mli": I + "val length : 'a t -> int\nval peek : 'a t -> 'a option\n",
       "test/test_fqueue.ml": '''let () =
  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in
  assert (Fqueue.length q = 2);
  assert (Fqueue.peek q = Some 2);
  assert (Fqueue.length q = 2);
  assert (Fqueue.peek Fqueue.empty = None)
'''}),
dict(id="of-list", text="Add of_list and to_list (front-to-back order preserved) to the queue, exported in the .mli, with a round-trip test.",
 partial={"lib/fqueue.ml": M + "\nlet of_list l = { front = l; back = [] }\n\nlet to_list q = q.front @ q.back\n",
          "lib/fqueue.mli": I + "val of_list : 'a list -> 'a t\nval to_list : 'a t -> 'a list\n",
          "test/test_fqueue.ml": T + "\nlet () =\n  let l = [ 1; 2; 3 ] in\n  assert (Fqueue.to_list (Fqueue.of_list l) = l)\n"},
 done={"lib/fqueue.ml": M + "\nlet of_list l = { front = l; back = [] }\n\nlet to_list q = q.front @ List.rev q.back\n",
       "lib/fqueue.mli": I + "val of_list : 'a list -> 'a t\nval to_list : 'a t -> 'a list\n",
       "test/test_fqueue.ml": T + "\nlet () =\n  let l = [ 1; 2; 3 ] in\n  assert (Fqueue.to_list (Fqueue.of_list l) = l);\n  assert (Fqueue.to_list (Fqueue.push 4 (Fqueue.of_list l)) = [ 1; 2; 3; 4 ])\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["length-peek"]["lib/fqueue.mli"] = I + "val length : 'a t -> int\nval peek : 'a t -> 'a option\n"
_P["length-peek"]["test/test_fqueue.ml"] = "let () =\n  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in\n  assert (Fqueue.length q = 2)\n"
