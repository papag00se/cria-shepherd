let () =
  let q = Fqueue.push 1 (Fqueue.push 2 Fqueue.empty) in
  assert (Fqueue.length q = 2);
  assert (Fqueue.peek q = Some 2);
  assert (Fqueue.length q = 2);
  assert (Fqueue.peek Fqueue.empty = None)
