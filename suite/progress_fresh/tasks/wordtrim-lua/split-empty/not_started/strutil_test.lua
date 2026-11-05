-- run with: lua strutil_test.lua
local u = require("strutil")

assert(u.trim("  hi") == "hi")
local parts = u.split("a,b,c", ",")
assert(#parts == 3 and parts[2] == "b")
print("ok")
