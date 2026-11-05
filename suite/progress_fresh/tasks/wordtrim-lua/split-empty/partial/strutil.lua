local M = {}

function M.trim(s)
  return (s:gsub("^%s+", ""))
end

function M.split(s, sep)
  local out = {}
  local start = 1
  while true do
    local i, j = string.find(s, sep, start, true)
    local piece = i and s:sub(start, i - 1) or s:sub(start)
    if piece ~= "" then out[#out + 1] = piece end
    if not i then return out end
    start = j + 1
  end
end

return M
