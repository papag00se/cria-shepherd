let () =
  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in
  match Fqueue.pop q with
  | Some (_, _) -> print_endline "popped"
  | None -> print_endline "empty"
