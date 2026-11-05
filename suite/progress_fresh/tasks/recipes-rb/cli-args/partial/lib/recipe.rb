class Recipe
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
    "#{name} (serves #{servings})\n" + lines.join("\n")
  end
end
