fun countWords(text: String): Map<String, Int> {
    val counts = mutableMapOf<String, Int>()
    for (w in text.split(" ")) {
        counts[w] = (counts[w] ?: 0) + 1
    }
    return counts
}
