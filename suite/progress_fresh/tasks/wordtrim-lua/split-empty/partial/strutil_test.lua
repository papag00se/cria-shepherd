local u = require("strutil")

assert(u.trim("  hi") == "hi")
local parts = u.split("a,b,c", ",")
assert(#parts == 3 and parts[2] == "b")
local d = u.split("a.b", ".")
assert(#d == 2 and d[2] == "b")
print("ok")
