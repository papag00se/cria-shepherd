defmodule Kv do
  def parse(text) do
    text
    |> String.split("\n")
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == "" or String.starts_with?(&1, "#")))
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=", parts: 2)
      {String.trim(k), String.trim(v)}
    end)
    |> Map.new()
  end
end
