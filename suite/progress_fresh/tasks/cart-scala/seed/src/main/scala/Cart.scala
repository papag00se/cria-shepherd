case class Item(sku: String, priceCents: Long, qty: Int)

class Cart(val items: List[Item] = Nil) {
  def add(item: Item): Cart = new Cart(items :+ item)

  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum
}
