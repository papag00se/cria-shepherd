from suite.progress_fresh.dsl import ed

SEED = {
"src/main/scala/Cart.scala": '''case class Item(sku: String, priceCents: Long, qty: Int)

class Cart(val items: List[Item] = Nil) {
  def add(item: Item): Cart = new Cart(items :+ item)

  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum
}
''',
"src/test/scala/CartSpec.scala": '''import org.scalatest.funsuite.AnyFunSuite

class CartSpec extends AnyFunSuite {
  test("total sums line totals") {
    val c = new Cart().add(Item("a", 250, 2)).add(Item("b", 100, 1))
    assert(c.totalCents == 600)
  }
}
''',
"README.md": "# cart\n\nA tiny immutable shopping cart.\n",
}
C = SEED["src/main/scala/Cart.scala"]
T = SEED["src/test/scala/CartSpec.scala"]
MERGE_OLD = "  def add(item: Item): Cart = new Cart(items :+ item)"
MERGE_NEW = '''  def add(item: Item): Cart = {
    val (same, other) = items.partition(_.sku == item.sku)
    val merged = same.headOption.map(s => s.copy(qty = s.qty + item.qty)).getOrElse(item)
    new Cart(other :+ merged)
  }'''
TASK = dict(extension=True, name="cart-scala", language="Scala", seed=SEED,
unrelated={"README.md": SEED["README.md"] + "\nRun the tests with `sbt test`.\n"},
reqs=[
dict(id="merge-sku", text="Adding an item whose sku is already in the cart should increase that line's quantity instead of appending a duplicate line.",
 partial={"src/main/scala/Cart.scala": ed(C, (MERGE_OLD, MERGE_NEW.replace("other :+ merged", "items :+ merged")))},
 done={"src/main/scala/Cart.scala": ed(C, (MERGE_OLD, MERGE_NEW))}),
dict(id="discount", text="Add a percent discount: Cart.discounted(percent: Int) returns the total in cents with the percent taken off, rounded down, and rejects percents outside 0..100 with an IllegalArgumentException. Test both.", ns=True,
 partial={"src/main/scala/Cart.scala": ed(C, ("  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum\n", "  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum\n\n  def discounted(percent: Int): Long = totalCents * (100 - percent) / 100\n")),
          "src/test/scala/CartSpec.scala": ed(T, ("  }\n}\n", "  }\n\n  test(\"discount\") {\n    val c = new Cart().add(Item(\"a\", 1000, 1))\n    assert(c.discounted(10) == 900)\n  }\n}\n"))},
 done={"src/main/scala/Cart.scala": ed(C, ("  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum\n", "  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum\n\n  def discounted(percent: Int): Long = {\n    require(percent >= 0 && percent <= 100, s\"bad percent $percent\")\n    totalCents * (100 - percent) / 100\n  }\n")),
       "src/test/scala/CartSpec.scala": ed(T, ("  }\n}\n", "  }\n\n  test(\"discount rounds down\") {\n    val c = new Cart().add(Item(\"a\", 999, 1))\n    assert(c.discounted(10) == 899)\n  }\n\n  test(\"discount rejects out-of-range percents\") {\n    val c = new Cart().add(Item(\"a\", 100, 1))\n    assertThrows[IllegalArgumentException](c.discounted(101))\n    assertThrows[IllegalArgumentException](c.discounted(-1))\n  }\n}\n"))}),
dict(id="remove-docs", text="Add Cart.remove(sku) that drops every line with that sku, test it, and document the method in README.md.",
 partial={"src/main/scala/Cart.scala": ed(C, ("  def totalCents", "  def remove(sku: String): Cart = new Cart(items.filterNot(_.sku == sku))\n\n  def totalCents")),
          "src/test/scala/CartSpec.scala": ed(T, ("  }\n}\n", "  }\n\n  test(\"remove drops the sku\") {\n    val c = new Cart().add(Item(\"a\", 250, 2)).add(Item(\"b\", 100, 1)).remove(\"a\")\n    assert(c.totalCents == 100)\n  }\n}\n"))},
 done={"src/main/scala/Cart.scala": ed(C, ("  def totalCents", "  def remove(sku: String): Cart = new Cart(items.filterNot(_.sku == sku))\n\n  def totalCents")),
       "src/test/scala/CartSpec.scala": ed(T, ("  }\n}\n", "  }\n\n  test(\"remove drops the sku\") {\n    val c = new Cart().add(Item(\"a\", 250, 2)).add(Item(\"b\", 100, 1)).remove(\"a\")\n    assert(c.totalCents == 100)\n  }\n}\n")),
       "README.md": SEED["README.md"] + "\n## API\n- `add(item)` appends a line.\n- `remove(sku)` drops every line with that sku.\n- `totalCents` sums all lines.\n"}),
])
