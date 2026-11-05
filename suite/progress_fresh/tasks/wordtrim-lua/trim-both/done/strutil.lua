local M = {}

function M.trim(s)
  return (s:match("^%s*(.-)%s*$"))
end

function M.split(s, sep)
  local out = {}
  for piece in string.gmatch(s, "([^" .. sep .. "]+)") do
    out[#out + 1] = piece
  end
  return out
end

return M
