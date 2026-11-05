from suite.progress_fresh.dsl import ed

SEED = {
"strutil.lua": '''local M = {}

function M.trim(s)
  return (s:gsub("^%s+", ""))
end

function M.split(s, sep)
  local out = {}
  for piece in string.gmatch(s, "([^" .. sep .. "]+)") do
    out[#out + 1] = piece
  end
  return out
end

return M
''',
"strutil_test.lua": '''local u = require("strutil")

assert(u.trim("  hi") == "hi")
local parts = u.split("a,b,c", ",")
assert(#parts == 3 and parts[2] == "b")
print("ok")
''',
}
S = SEED["strutil.lua"]
T = SEED["strutil_test.lua"]
TASK = dict(extension=True, name="wordtrim-lua", language="Lua", seed=SEED,
unrelated={"strutil_test.lua": "-- run with: lua strutil_test.lua\n" + T},
reqs=[
dict(id="trim-both", text="trim only strips leading whitespace. Make it strip trailing whitespace too and return the empty string for an all-whitespace input; add tests.",
 partial={"strutil.lua": ed(S, ('  return (s:gsub("^%s+", ""))', '  return (s:gsub("%s+$", ""))')),
          "strutil_test.lua": ed(T, ('print("ok")', 'assert(u.trim("hi  ") == "hi")\nprint("ok")'))},
 done={"strutil.lua": ed(S, ('  return (s:gsub("^%s+", ""))', '  return (s:match("^%s*(.-)%s*$"))')),
       "strutil_test.lua": ed(T, ('print("ok")', 'assert(u.trim("hi  ") == "hi")\nassert(u.trim("  hi \\t") == "hi")\nassert(u.trim("   ") == "")\nprint("ok")'))}),
dict(id="split-empty", text="split drops empty fields (\"a,,b\" gives two pieces) and breaks for magic separators like '.'. Keep empty fields and escape the separator so \"a.b\" splits on '.'; test both.", ns=True,
 partial={"strutil.lua": ed(S, ('''  local out = {}
  for piece in string.gmatch(s, "([^" .. sep .. "]+)") do
    out[#out + 1] = piece
  end
  return out''', '''  local out = {}
  local start = 1
  while true do
    local i, j = string.find(s, sep, start, true)
    local piece = i and s:sub(start, i - 1) or s:sub(start)
    if piece ~= "" then out[#out + 1] = piece end
    if not i then return out end
    start = j + 1
  end''')),
          "strutil_test.lua": ed(T, ('print("ok")', 'local d = u.split("a.b", ".")\nassert(#d == 2 and d[2] == "b")\nprint("ok")'))},
 done={"strutil.lua": ed(S, ('''  local out = {}
  for piece in string.gmatch(s, "([^" .. sep .. "]+)") do
    out[#out + 1] = piece
  end
  return out''', '''  local out = {}
  local start = 1
  while true do
    local i, j = string.find(s, sep, start, true)
    if not i then
      out[#out + 1] = s:sub(start)
      return out
    end
    out[#out + 1] = s:sub(start, i - 1)
    start = j + 1
  end''')),
       "strutil_test.lua": ed(T, ('print("ok")', 'local e = u.split("a,,b", ",")\nassert(#e == 3 and e[2] == "")\nlocal d = u.split("a.b", ".")\nassert(#d == 2 and d[2] == "b")\nprint("ok")'))}),
dict(id="starts-with", text="Add startswith(s, prefix) and endswith(s, suffix) to the module (plain comparison, no patterns) with a test for each, including an empty prefix.",
 partial={"strutil.lua": ed(S, ("return M\n", 'function M.startswith(s, prefix)\n  return s:sub(1, #prefix) == prefix\nend\n\nfunction M.endswith(s, suffix)\n  return s:sub(-#suffix) == suffix\nend\n\nreturn M\n')),
          "strutil_test.lua": ed(T, ('print("ok")', 'assert(u.startswith("hello", "he") and not u.startswith("hello", "lo"))\nassert(u.endswith("hello", "lo") and not u.endswith("hello", "he"))\nprint("ok")'))},
 done={"strutil.lua": ed(S, ("return M\n", 'function M.startswith(s, prefix)\n  return s:sub(1, #prefix) == prefix\nend\n\nfunction M.endswith(s, suffix)\n  return suffix == "" or s:sub(-#suffix) == suffix\nend\n\nreturn M\n')),
       "strutil_test.lua": ed(T, ('print("ok")', 'assert(u.startswith("hello", "he") and not u.startswith("hello", "lo"))\nassert(u.startswith("hello", ""))\nassert(u.endswith("hello", "lo") and not u.endswith("hello", "he"))\nassert(u.endswith("hello", ""))\nprint("ok")'))}),
])
