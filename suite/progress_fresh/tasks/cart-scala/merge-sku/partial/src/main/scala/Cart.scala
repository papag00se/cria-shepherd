case class Item(sku: String, priceCents: Long, qty: Int)

class Cart(val items: List[Item] = Nil) {
  def add(item: Item): Cart = {
    val (same, other) = items.partition(_.sku == item.sku)
    val merged = same.headOption.map(s => s.copy(qty = s.qty + item.qty)).getOrElse(item)
    new Cart(items :+ merged)
  }

  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum
}
