type 'a t = { front : 'a list; back : 'a list }

let empty = { front = []; back = [] }

let push x q = { q with back = x :: q.back }

let pop q =
  match q.front with
  | x :: rest -> Some (x, { q with front = rest })
  | [] -> None
