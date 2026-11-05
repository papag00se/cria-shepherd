defmodule KvTest do
  use ExUnit.Case

  test "parses pairs" do
    assert Kv.parse("a=1\nb=2") == %{"a" => "1", "b" => "2"}
  end

  test "parse skips lines without =" do
    assert Kv.parse("a=1\nnonsense") == %{"a" => "1"}
  end

  test "parse_strict reports the first bad line" do
    assert Kv.parse_strict("a=1\nb=2\noops\nc") == {:error, 3}
    assert Kv.parse_strict("a=1") == {:ok, %{"a" => "1"}}
  end
end
