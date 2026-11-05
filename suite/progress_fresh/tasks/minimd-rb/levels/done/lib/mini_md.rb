module MiniMd
  def self.render(text)
    text.lines.map { |line| render_line(line.chomp) }.join("\n")
  end

  def self.render_line(line)
    if (m = line.match(/\A(\#{1,6}) (.*)/))
      "<h#{m[1].size}>#{m[2]}</h#{m[1].size}>"
    else
      "<p>#{line}</p>"
    end
  end
end
