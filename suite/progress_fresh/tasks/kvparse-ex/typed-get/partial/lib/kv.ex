defmodule Kv do
  def parse(text) do
    text
    |> String.split("\n")
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=")
      {k, v}
    end)
    |> Map.new()
  end

  def get_int(map, key, default) do
    case Map.fetch(map, key) do
      {:ok, v} -> String.to_integer(v)
      :error -> default
    end
  end
end
