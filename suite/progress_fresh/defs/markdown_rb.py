from suite.progress_fresh.dsl import ed

SEED = {
"lib/mini_md.rb": '''module MiniMd
  def self.render(text)
    text.lines.map { |line| render_line(line.chomp) }.join("\\n")
  end

  def self.render_line(line)
    if line.start_with?("# ")
      "<h1>#{line[2..]}</h1>"
    else
      "<p>#{line}</p>"
    end
  end
end
''',
"test/mini_md_test.rb": '''require "minitest/autorun"
require_relative "../lib/mini_md"

class MiniMdTest < Minitest::Test
  def test_heading
    assert_equal "<h1>Hi</h1>", MiniMd.render("# Hi")
  end

  def test_paragraph
    assert_equal "<p>text</p>", MiniMd.render("text")
  end
end
''',
"README.md": "# mini_md\n\nA very small markdown renderer.\n",
}
L = SEED["lib/mini_md.rb"]
T = SEED["test/mini_md_test.rb"]
INL = '''
  def self.inline(s)
    s.gsub(/\\*\\*(.+?)\\*\\*/, '<strong>\\1</strong>')
     .gsub(/\\*(.+?)\\*/, '<em>\\1</em>')
  end
'''
TASK = dict(extension=True, name="minimd-rb", language="Ruby", seed=SEED,
unrelated={"README.md": SEED["README.md"] + "\nRun `ruby test/mini_md_test.rb`.\n"},
reqs=[
dict(id="levels", text="Support headings h1 through h6 (\"## Title\" -> <h2>Title</h2>) and leave lines such as \"#nospace\" as paragraphs; add tests for h2, h6 and the no-space case.",
 partial={"lib/mini_md.rb": ed(L, ('    if line.start_with?("# ")\n      "<h1>#{line[2..]}</h1>"', '    if (m = line.match(/\\A(\\#{1,6}) (.*)/))\n      "<h#{m[1].size}>#{m[2]}</h#{m[1].size}>"'))},
 done={"lib/mini_md.rb": ed(L, ('    if line.start_with?("# ")\n      "<h1>#{line[2..]}</h1>"', '    if (m = line.match(/\\A(\\#{1,6}) (.*)/))\n      "<h#{m[1].size}>#{m[2]}</h#{m[1].size}>"')),
       "test/mini_md_test.rb": ed(T, ("  end\nend\n", "  end\n" + '''
  def test_levels
    assert_equal "<h2>Title</h2>", MiniMd.render("## Title")
    assert_equal "<h6>Deep</h6>", MiniMd.render("###### Deep")
  end

  def test_hash_without_space_is_a_paragraph
    assert_equal "<p>#nospace</p>", MiniMd.render("#nospace")
  end
end
'''))}),
dict(id="inline", text="Render **bold** as <strong> and *italic* as <em> inside paragraphs and headings, with a test for each and for both in one line.",
 partial={"lib/mini_md.rb": ed(L, ("  def self.render_line(line)", INL.lstrip("\n") + "\n  def self.render_line(line)"), ('"<p>#{line}</p>"', '"<p>#{inline(line)}</p>"'))},
 done={"lib/mini_md.rb": ed(L, ("  def self.render_line(line)", INL.lstrip("\n") + "\n  def self.render_line(line)"), ('"<p>#{line}</p>"', '"<p>#{inline(line)}</p>"'), ('"<h1>#{line[2..]}</h1>"', '"<h1>#{inline(line[2..])}</h1>"')),
       "test/mini_md_test.rb": ed(T, ("  end\nend\n", "  end\n" + '''
  def test_bold_and_italic
    assert_equal "<p><strong>a</strong></p>", MiniMd.render("**a**")
    assert_equal "<p><em>a</em></p>", MiniMd.render("*a*")
    assert_equal "<p><strong>a</strong> and <em>b</em></p>", MiniMd.render("**a** and *b*")
  end

  def test_inline_in_heading
    assert_equal "<h1>Hi <em>you</em></h1>", MiniMd.render("# Hi *you*")
  end
end
'''))}),
dict(id="escape-docs", text="Escape <, > and & in text before wrapping it in tags so input cannot inject HTML, test it, and add a Usage/Security note to the README describing the escaping.",
 partial={"lib/mini_md.rb": ed(L, ("  def self.render_line(line)\n", "  def self.escape(s)\n    s.gsub(\"&\", \"&amp;\").gsub(\"<\", \"&lt;\").gsub(\">\", \"&gt;\")\n  end\n\n  def self.render_line(line)\n    line = escape(line)\n")),
          "test/mini_md_test.rb": ed(T, ("  end\nend\n", "  end\n" + "\n  def test_escapes\n    assert_equal \"<p>&lt;b&gt;</p>\", MiniMd.render(\"<b>\")\n  end\nend\n"))},
 done={"lib/mini_md.rb": ed(L, ("  def self.render_line(line)\n", "  def self.escape(s)\n    s.gsub(\"&\", \"&amp;\").gsub(\"<\", \"&lt;\").gsub(\">\", \"&gt;\")\n  end\n\n  def self.render_line(line)\n    line = escape(line)\n")),
       "test/mini_md_test.rb": ed(T, ("  end\nend\n", "  end\n" + "\n  def test_escapes\n    assert_equal \"<p>&lt;b&gt;</p>\", MiniMd.render(\"<b>\")\n    assert_equal \"<p>a &amp; b</p>\", MiniMd.render(\"a & b\")\n  end\nend\n")),
       "README.md": SEED["README.md"] + "\n## Security\n\n`<`, `>` and `&` in the input are HTML-escaped before tags are added, so rendered output cannot contain injected markup.\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["levels"]["test/mini_md_test.rb"] = ed(T, ("  end\nend\n", "  end\n\n  def test_h2\n    assert_equal \"<h2>Title</h2>\", MiniMd.render(\"## Title\")\n  end\nend\n"))
_P["inline"]["test/mini_md_test.rb"] = ed(T, ("  end\nend\n", "  end\n\n  def test_bold\n    assert_equal \"<p><strong>a</strong></p>\", MiniMd.render(\"**a**\")\n  end\nend\n"))
