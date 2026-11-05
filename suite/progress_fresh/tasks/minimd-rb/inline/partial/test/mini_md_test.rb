require "minitest/autorun"
require_relative "../lib/mini_md"

class MiniMdTest < Minitest::Test
  def test_heading
    assert_equal "<h1>Hi</h1>", MiniMd.render("# Hi")
  end

  def test_paragraph
    assert_equal "<p>text</p>", MiniMd.render("text")
  end

  def test_bold
    assert_equal "<p><strong>a</strong></p>", MiniMd.render("**a**")
  end
end
