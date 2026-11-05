defmodule KvTest do
  use ExUnit.Case

  test "parses pairs" do
    assert Kv.parse("a=1\nb=2") == %{"a" => "1", "b" => "2"}
  end

  test "get_int parses, defaults and rejects" do
    assert Kv.get_int(%{"n" => "4"}, "n", 0) == 4
    assert Kv.get_int(%{}, "n", 9) == 9
    assert_raise ArgumentError, fn -> Kv.get_int(%{"n" => "4x"}, "n", 0) end
  end
end
