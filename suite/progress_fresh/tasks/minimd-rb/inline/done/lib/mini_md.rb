module MiniMd
  def self.render(text)
    text.lines.map { |line| render_line(line.chomp) }.join("\n")
  end

  def self.inline(s)
    s.gsub(/\*\*(.+?)\*\*/, '<strong>\1</strong>')
     .gsub(/\*(.+?)\*/, '<em>\1</em>')
  end

  def self.render_line(line)
    if line.start_with?("# ")
      "<h1>#{inline(line[2..])}</h1>"
    else
      "<p>#{inline(line)}</p>"
    end
  end
end
