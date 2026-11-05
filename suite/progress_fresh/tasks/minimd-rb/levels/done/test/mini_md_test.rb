require "minitest/autorun"
require_relative "../lib/mini_md"

class MiniMdTest < Minitest::Test
  def test_heading
    assert_equal "<h1>Hi</h1>", MiniMd.render("# Hi")
  end

  def test_paragraph
    assert_equal "<p>text</p>", MiniMd.render("text")
  end

  def test_levels
    assert_equal "<h2>Title</h2>", MiniMd.render("## Title")
    assert_equal "<h6>Deep</h6>", MiniMd.render("###### Deep")
  end

  def test_hash_without_space_is_a_paragraph
    assert_equal "<p>#nospace</p>", MiniMd.render("#nospace")
  end
end
