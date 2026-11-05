fun countWords(text: String, stopwords: Set<String> = emptySet()): Map<String, Int> {
    val counts = mutableMapOf<String, Int>()
    for (w in text.split(" ")) {
        if (w in stopwords) continue
        counts[w] = (counts[w] ?: 0) + 1
    }
    return counts
}
