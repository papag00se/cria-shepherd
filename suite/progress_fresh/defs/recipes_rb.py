TASK = dict(name="recipes-rb", language="Ruby", seed={
"Gemfile": 'source "https://rubygems.org"\n\ngem "minitest"\n',
"lib/recipe.rb": '''class Recipe
  attr_reader :name, :servings, :ingredients

  def initialize(name, servings, ingredients)
    @name = name
    @servings = servings
    @ingredients = ingredients # { "flour" => [2.0, "cup"] }
  end

  def scale(target)
    factor = target / servings
    scaled = ingredients.transform_values { |qty, unit| [qty * factor, unit] }
    Recipe.new(name, target, scaled)
  end

  def to_s
    lines = ingredients.map { |n, (q, u)| "#{q} #{u} #{n}" }
    "#{name} (serves #{servings})\\n" + lines.join("\\n")
  end
end
''',
"bin/scale": '''#!/usr/bin/env ruby
require_relative "../lib/recipe"

r = Recipe.new("pancakes", 4, { "flour" => [2.0, "cup"], "milk" => [1.5, "cup"] })
puts r.scale(Integer(ARGV.fetch(0, 4))).to_s
''',
"test/recipe_test.rb": '''require "minitest/autorun"
require_relative "../lib/recipe"

class RecipeTest < Minitest::Test
  def test_scale_doubles
    r = Recipe.new("x", 2, { "a" => [1.0, "cup"] }).scale(4)
    assert_equal 2.0, r.ingredients["a"][0]
  end
end
''',
}, unrelated={"Gemfile": 'source "https://rubygems.org"\n\ngem "minitest", "~> 5.20"\n'},
reqs=[
dict(id="integer-division", text="Recipe#scale truncates when both servings and target are integers (scaling 4 servings to 6 gives a factor of 1). Fix it so the factor is a true ratio.",
 partial={"test/recipe_test.rb": '''require "minitest/autorun"
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
'''},
 done={"lib/recipe.rb": '''class Recipe
  attr_reader :name, :servings, :ingredients

  def initialize(name, servings, ingredients)
    @name = name
    @servings = servings
    @ingredients = ingredients # { "flour" => [2.0, "cup"] }
  end

  def scale(target)
    factor = target.to_f / servings
    scaled = ingredients.transform_values { |qty, unit| [qty * factor, unit] }
    Recipe.new(name, target, scaled)
  end

  def to_s
    lines = ingredients.map { |n, (q, u)| "#{q} #{u} #{n}" }
    "#{name} (serves #{servings})\\n" + lines.join("\\n")
  end
end
''', "test/recipe_test.rb": '''require "minitest/autorun"
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
'''}),
dict(id="format-quantities", text="Make to_s print tidy quantities: whole numbers without a decimal point (2 cup flour) and everything else rounded to at most two decimals (1.33 cup milk).",
 partial={"lib/recipe.rb": '''class Recipe
  attr_reader :name, :servings, :ingredients

  def initialize(name, servings, ingredients)
    @name = name
    @servings = servings
    @ingredients = ingredients # { "flour" => [2.0, "cup"] }
  end

  def scale(target)
    factor = target / servings
    scaled = ingredients.transform_values { |qty, unit| [qty * factor, unit] }
    Recipe.new(name, target, scaled)
  end

  def to_s
    lines = ingredients.map { |n, (q, u)| "#{q.round(2)} #{u} #{n}" }
    "#{name} (serves #{servings})\\n" + lines.join("\\n")
  end
end
'''},
 done={"lib/recipe.rb": '''class Recipe
  attr_reader :name, :servings, :ingredients

  def initialize(name, servings, ingredients)
    @name = name
    @servings = servings
    @ingredients = ingredients # { "flour" => [2.0, "cup"] }
  end

  def scale(target)
    factor = target / servings
    scaled = ingredients.transform_values { |qty, unit| [qty * factor, unit] }
    Recipe.new(name, target, scaled)
  end

  def to_s
    lines = ingredients.map { |n, (q, u)| "#{format_qty(q)} #{u} #{n}" }
    "#{name} (serves #{servings})\\n" + lines.join("\\n")
  end

  private

  def format_qty(q)
    r = q.round(2)
    r == r.to_i ? r.to_i.to_s : r.to_s
  end
end
'''}),
dict(id="cli-args", text="Make bin/scale usable: take the recipe servings target from ARGV and print a usage message to stderr and exit 1 when the argument is missing or not a positive integer.",
 partial={"bin/scale": '''#!/usr/bin/env ruby
require_relative "../lib/recipe"

target = ARGV.first
abort "usage: scale SERVINGS" unless target

r = Recipe.new("pancakes", 4, { "flour" => [2.0, "cup"], "milk" => [1.5, "cup"] })
puts r.scale(Integer(target)).to_s
'''},
 done={"bin/scale": '''#!/usr/bin/env ruby
require_relative "../lib/recipe"

target = Integer(ARGV.first, exception: false)
unless ARGV.size == 1 && target && target.positive?
  warn "usage: scale SERVINGS   (a positive integer)"
  exit 1
end

r = Recipe.new("pancakes", 4, { "flour" => [2.0, "cup"], "milk" => [1.5, "cup"] })
puts r.scale(target).to_s
'''}),
])
