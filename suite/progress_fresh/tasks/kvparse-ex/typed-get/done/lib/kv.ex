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
      {:ok, v} ->
        case Integer.parse(v) do
          {n, ""} -> n
          _ -> raise ArgumentError, "not an integer: #{v}"
        end

      :error ->
        default
    end
  end
end
