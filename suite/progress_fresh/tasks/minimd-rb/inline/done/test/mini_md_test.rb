require "minitest/autorun"
require_relative "../lib/mini_md"

class MiniMdTest < Minitest::Test
  def test_heading
    assert_equal "<h1>Hi</h1>", MiniMd.render("# Hi")
  end

  def test_paragraph
    assert_equal "<p>text</p>", MiniMd.render("text")
  end

  def test_bold_and_italic
    assert_equal "<p><strong>a</strong></p>", MiniMd.render("**a**")
    assert_equal "<p><em>a</em></p>", MiniMd.render("*a*")
    assert_equal "<p><strong>a</strong> and <em>b</em></p>", MiniMd.render("**a** and *b*")
  end

  def test_inline_in_heading
    assert_equal "<h1>Hi <em>you</em></h1>", MiniMd.render("# Hi *you*")
  end
end
