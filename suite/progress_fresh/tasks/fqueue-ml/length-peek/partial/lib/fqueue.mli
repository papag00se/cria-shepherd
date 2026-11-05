type 'a t

val empty : 'a t
val push : 'a -> 'a t -> 'a t
val pop : 'a t -> ('a * 'a t) option
val length : 'a t -> int
val peek : 'a t -> 'a option
