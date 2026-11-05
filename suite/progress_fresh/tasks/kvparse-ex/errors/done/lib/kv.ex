defmodule Kv do
  def parse(text) do
    text
    |> String.split("\n")
    |> Enum.flat_map(fn line ->
      case String.split(line, "=", parts: 2) do
        [k, v] -> [{k, v}]
        _ -> []
      end
    end)
    |> Map.new()
  end

  def parse_strict(text) do
    text
    |> String.split("\n")
    |> Enum.with_index(1)
    |> Enum.reduce_while({:ok, %{}}, fn {line, n}, {:ok, acc} ->
      case String.split(line, "=", parts: 2) do
        [k, v] -> {:cont, {:ok, Map.put(acc, k, v)}}
        _ -> {:halt, {:error, n}}
      end
    end)
  end
end
