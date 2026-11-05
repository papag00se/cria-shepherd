local M = {}

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

function M.startswith(s, prefix)
  return s:sub(1, #prefix) == prefix
end

function M.endswith(s, suffix)
  return s:sub(-#suffix) == suffix
end

return M
