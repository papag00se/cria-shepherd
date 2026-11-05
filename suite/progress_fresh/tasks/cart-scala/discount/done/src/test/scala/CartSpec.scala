import org.scalatest.funsuite.AnyFunSuite

class CartSpec extends AnyFunSuite {
  test("total sums line totals") {
    val c = new Cart().add(Item("a", 250, 2)).add(Item("b", 100, 1))
    assert(c.totalCents == 600)
  }

  test("discount rounds down") {
    val c = new Cart().add(Item("a", 999, 1))
    assert(c.discounted(10) == 899)
  }

  test("discount rejects out-of-range percents") {
    val c = new Cart().add(Item("a", 100, 1))
    assertThrows[IllegalArgumentException](c.discounted(101))
    assertThrows[IllegalArgumentException](c.discounted(-1))
  }
}
