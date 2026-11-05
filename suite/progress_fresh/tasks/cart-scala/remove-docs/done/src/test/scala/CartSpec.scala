import org.scalatest.funsuite.AnyFunSuite

class CartSpec extends AnyFunSuite {
  test("total sums line totals") {
    val c = new Cart().add(Item("a", 250, 2)).add(Item("b", 100, 1))
    assert(c.totalCents == 600)
  }

  test("remove drops the sku") {
    val c = new Cart().add(Item("a", 250, 2)).add(Item("b", 100, 1)).remove("a")
    assert(c.totalCents == 100)
  }
}
