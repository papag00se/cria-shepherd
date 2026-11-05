local u = require("strutil")

assert(u.trim("  hi") == "hi")
local parts = u.split("a,b,c", ",")
assert(#parts == 3 and parts[2] == "b")
assert(u.trim("hi  ") == "hi")
assert(u.trim("  hi \t") == "hi")
assert(u.trim("   ") == "")
print("ok")
