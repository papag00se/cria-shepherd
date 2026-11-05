case class Item(sku: String, priceCents: Long, qty: Int)

class Cart(val items: List[Item] = Nil) {
  def add(item: Item): Cart = new Cart(items :+ item)

  def totalCents: Long = items.map(i => i.priceCents * i.qty).sum

  def discounted(percent: Int): Long = {
    require(percent >= 0 && percent <= 100, s"bad percent $percent")
    totalCents * (100 - percent) / 100
  }
}
