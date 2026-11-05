let () =
  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in
  match Fqueue.pop q with
  | Some (_, _) -> print_endline "popped"
  | None -> print_endline "empty"

let () =
  let l = [ 1; 2; 3 ] in
  assert (Fqueue.to_list (Fqueue.of_list l) = l)
