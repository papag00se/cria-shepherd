type 'a t = { front : 'a list; back : 'a list }

let empty = { front = []; back = [] }

let push x q = { q with back = x :: q.back }

let pop q =
  match q.front with
  | x :: rest -> Some (x, { q with front = rest })
  | [] -> (
      match List.rev q.back with
      | [] -> None
      | x :: rest -> Some (x, { front = rest; back = [] }))

let length q = List.length q.front + List.length q.back

let peek q =
  match q.front with
  | x :: _ -> Some x
  | [] -> ( match List.rev q.back with x :: _ -> Some x | [] -> None)
