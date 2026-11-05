fun countWords(text: String): Map<String, Int> {
    val counts = mutableMapOf<String, Int>()
    for (w in text.split(" ")) {
        counts[w] = (counts[w] ?: 0) + 1
    }
    return counts
}

fun topWords(text: String, n: Int): List<Pair<String, Int>> =
    countWords(text).toList().sortedWith(compareBy({ -it.second }, { it.first })).take(n)
