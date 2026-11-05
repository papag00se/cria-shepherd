defmodule Kv do
  @doc false
  def parse(text) do
    text
    |> String.split("\n")
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=")
      {k, v}
    end)
    |> Map.new()
  end
end
