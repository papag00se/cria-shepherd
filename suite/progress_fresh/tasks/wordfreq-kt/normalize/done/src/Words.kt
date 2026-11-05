fun countWords(text: String): Map<String, Int> {
    val counts = mutableMapOf<String, Int>()
    for (w in text.lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }) {
        counts[w] = (counts[w] ?: 0) + 1
    }
    return counts
}
