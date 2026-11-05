local M = {}

function M.trim(s)
  return (s:gsub("^%s+", ""))
end

function M.split(s, sep)
  local out = {}
  local start = 1
  while true do
    local i, j = string.find(s, sep, start, true)
    if not i then
      out[#out + 1] = s:sub(start)
      return out
    end
    out[#out + 1] = s:sub(start, i - 1)
    start = j + 1
  end
end

return M
