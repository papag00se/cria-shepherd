require "minitest/autorun"
require_relative "../lib/recipe"

class RecipeTest < Minitest::Test
  def test_scale_doubles
    r = Recipe.new("x", 2, { "a" => [1.0, "cup"] }).scale(4)
    assert_equal 2.0, r.ingredients["a"][0]
  end

  def test_scale_non_multiple
    r = Recipe.new("x", 4, { "a" => [2.0, "cup"] }).scale(6)
    assert_equal 3.0, r.ingredients["a"][0]
  end
end
