defmodule Kv do
  def parse(text) do
    text
    |> String.split("\n")
    |> Enum.reject(&(String.trim(&1) == "" or String.starts_with?(&1, "#")))
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=")
      {String.trim(k), String.trim(v)}
    end)
    |> Map.new()
  end
end
