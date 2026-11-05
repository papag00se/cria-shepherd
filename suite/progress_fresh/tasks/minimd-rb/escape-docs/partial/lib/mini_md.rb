module MiniMd
  def self.render(text)
    text.lines.map { |line| render_line(line.chomp) }.join("\n")
  end

  def self.escape(s)
    s.gsub("&", "&amp;").gsub("<", "&lt;").gsub(">", "&gt;")
  end

  def self.render_line(line)
    line = escape(line)
    if line.start_with?("# ")
      "<h1>#{line[2..]}</h1>"
    else
      "<p>#{line}</p>"
    end
  end
end
