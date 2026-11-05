from suite.progress_fresh.dsl import ed

SEED = {
"lib/kv.ex": '''defmodule Kv do
  def parse(text) do
    text
    |> String.split("\\n")
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=")
      {k, v}
    end)
    |> Map.new()
  end
end
''',
"test/kv_test.exs": '''defmodule KvTest do
  use ExUnit.Case

  test "parses pairs" do
    assert Kv.parse("a=1\\nb=2") == %{"a" => "1", "b" => "2"}
  end
end
''',
}
K = SEED["lib/kv.ex"]
T = SEED["test/kv_test.exs"]
TASK = dict(extension=True, name="kvparse-ex", language="Elixir", seed=SEED,
unrelated={"lib/kv.ex": ed(K, ("  def parse", "  @doc false\n  def parse"))},
reqs=[
dict(id="tolerant", text="Kv.parse must skip blank lines and comment lines starting with #, trim whitespace around keys and values, and keep any '=' inside a value (only the first '=' separates key from value).",
 partial={"lib/kv.ex": '''defmodule Kv do
  def parse(text) do
    text
    |> String.split("\\n")
    |> Enum.reject(&(String.trim(&1) == "" or String.starts_with?(&1, "#")))
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=")
      {String.trim(k), String.trim(v)}
    end)
    |> Map.new()
  end
end
'''},
 done={"lib/kv.ex": '''defmodule Kv do
  def parse(text) do
    text
    |> String.split("\\n")
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == "" or String.starts_with?(&1, "#")))
    |> Enum.map(fn line ->
      [k, v] = String.split(line, "=", parts: 2)
      {String.trim(k), String.trim(v)}
    end)
    |> Map.new()
  end
end
'''}),
dict(id="errors", text="Lines without an '=' should not crash parse/1. Add parse_strict/1 returning {:ok, map} or {:error, line_number} for the first malformed line, and test the error case.", ns=True,
 partial={"lib/kv.ex": ed(K, ("  end\nend\n", "  end\n\n  def parse_strict(text) do\n    text\n    |> String.split(\"\\n\")\n    |> Enum.with_index(1)\n    |> Enum.reduce_while({:ok, %{}}, fn {line, n}, {:ok, acc} ->\n      case String.split(line, \"=\", parts: 2) do\n        [k, v] -> {:cont, {:ok, Map.put(acc, k, v)}}\n        _ -> {:halt, {:error, n}}\n      end\n    end)\n  end\nend\n")),
          "test/kv_test.exs": ed(T, ("  end\nend\n", "  end\n\n  test \"parse_strict reports the first bad line\" do\n    assert Kv.parse_strict(\"a=1\\nb=2\\noops\\nc\") == {:error, 3}\n  end\nend\n"))},
 done={"lib/kv.ex": '''defmodule Kv do
  def parse(text) do
    text
    |> String.split("\\n")
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
    |> String.split("\\n")
    |> Enum.with_index(1)
    |> Enum.reduce_while({:ok, %{}}, fn {line, n}, {:ok, acc} ->
      case String.split(line, "=", parts: 2) do
        [k, v] -> {:cont, {:ok, Map.put(acc, k, v)}}
        _ -> {:halt, {:error, n}}
      end
    end)
  end
end
''', "test/kv_test.exs": ed(T, ("  end\nend\n", "  end\n\n  test \"parse skips lines without =\" do\n    assert Kv.parse(\"a=1\\nnonsense\") == %{\"a\" => \"1\"}\n  end\n\n  test \"parse_strict reports the first bad line\" do\n    assert Kv.parse_strict(\"a=1\\nb=2\\noops\\nc\") == {:error, 3}\n    assert Kv.parse_strict(\"a=1\") == {:ok, %{\"a\" => \"1\"}}\n  end\nend\n"))}),
dict(id="typed-get", text="Add Kv.get_int(map, key, default) that returns the value as an integer, the default when the key is missing, and raises ArgumentError when the value is not an integer. Test all three paths.",
 partial={"lib/kv.ex": ed(K, ("  end\nend\n", "  end\n\n  def get_int(map, key, default) do\n    case Map.fetch(map, key) do\n      {:ok, v} -> String.to_integer(v)\n      :error -> default\n    end\n  end\nend\n")),
          "test/kv_test.exs": ed(T, ("  end\nend\n", "  end\n\n  test \"get_int\" do\n    assert Kv.get_int(%{\"n\" => \"4\"}, \"n\", 0) == 4\n    assert Kv.get_int(%{}, \"n\", 9) == 9\n  end\nend\n"))},
 done={"lib/kv.ex": ed(K, ("  end\nend\n", "  end\n\n  def get_int(map, key, default) do\n    case Map.fetch(map, key) do\n      {:ok, v} ->\n        case Integer.parse(v) do\n          {n, \"\"} -> n\n          _ -> raise ArgumentError, \"not an integer: #{v}\"\n        end\n\n      :error ->\n        default\n    end\n  end\nend\n")),
       "test/kv_test.exs": ed(T, ("  end\nend\n", "  end\n\n  test \"get_int parses, defaults and rejects\" do\n    assert Kv.get_int(%{\"n\" => \"4\"}, \"n\", 0) == 4\n    assert Kv.get_int(%{}, \"n\", 9) == 9\n    assert_raise ArgumentError, fn -> Kv.get_int(%{\"n\" => \"4x\"}, \"n\", 0) end\n  end\nend\n"))}),
])
