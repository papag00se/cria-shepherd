local u = require("strutil")

assert(u.trim("  hi") == "hi")
local parts = u.split("a,b,c", ",")
assert(#parts == 3 and parts[2] == "b")
assert(u.startswith("hello", "he") and not u.startswith("hello", "lo"))
assert(u.endswith("hello", "lo") and not u.endswith("hello", "he"))
print("ok")
