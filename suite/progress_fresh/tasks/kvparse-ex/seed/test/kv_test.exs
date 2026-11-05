defmodule KvTest do
  use ExUnit.Case

  test "parses pairs" do
    assert Kv.parse("a=1\nb=2") == %{"a" => "1", "b" => "2"}
  end
end
