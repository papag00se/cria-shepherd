from suite.progress_fresh.dsl import ed

SEED = {
"src/Words.kt": '''fun countWords(text: String): Map<String, Int> {
    val counts = mutableMapOf<String, Int>()
    for (w in text.split(" ")) {
        counts[w] = (counts[w] ?: 0) + 1
    }
    return counts
}
''',
"src/Main.kt": '''fun main(args: Array<String>) {
    val text = args.joinToString(" ")
    for ((w, c) in countWords(text)) println("$w $c")
}
''',
"src/WordsTest.kt": '''import kotlin.test.Test
import kotlin.test.assertEquals

class WordsTest {
    @Test
    fun countsRepeats() {
        assertEquals(2, countWords("a b a")["a"])
    }
}
''',
}
W = SEED["src/Words.kt"]
M = SEED["src/Main.kt"]
T = SEED["src/WordsTest.kt"]
TOP = '''
fun topWords(text: String, n: Int): List<Pair<String, Int>> =
    countWords(text).toList().sortedWith(compareBy({ -it.second }, { it.first })).take(n)
'''
TASK = dict(extension=True, name="wordfreq-kt", language="Kotlin", seed=SEED,
unrelated={"src/Main.kt": ed(M, ("fun main", "// prints one \"word count\" pair per line\nfun main"))},
reqs=[
dict(id="normalize", text="countWords must be case-insensitive and must split on any run of whitespace, so \"Go  go\\tGO\" counts three occurrences of \"go\" and never produces an empty-string key.",
 partial={"src/Words.kt": ed(W, ("text.split(\" \")", "text.lowercase().split(\" \")"))},
 done={"src/Words.kt": ed(W, ("text.split(\" \")", "text.lowercase().split(Regex(\"\\\\s+\")).filter { it.isNotEmpty() }"))}),
dict(id="top-n", text="Add topWords(text, n) returning the n most frequent (word, count) pairs, ties broken alphabetically, and add a --top N option to main that prints only those.", ns=True,
 partial={"src/Words.kt": W + TOP, "src/Main.kt": '''fun main(args: Array<String>) {
    val top = args.indexOf("--top").let { if (it >= 0) args[it + 1].toInt() else null }
    val text = args.joinToString(" ")
    val pairs = if (top != null) topWords(text, top) else countWords(text).toList()
    for ((w, c) in pairs) println("$w $c")
}
'''},
 done={"src/Words.kt": W + TOP, "src/Main.kt": '''fun main(args: Array<String>) {
    val top = args.indexOf("--top").let { if (it >= 0) args[it + 1].toInt() else null }
    val rest = if (top != null) args.toList().filterIndexed { i, _ -> i != args.indexOf("--top") && i != args.indexOf("--top") + 1 } else args.toList()
    val text = rest.joinToString(" ")
    val pairs = if (top != null) topWords(text, top) else countWords(text).toList()
    for ((w, c) in pairs) println("$w $c")
}
'''}),
dict(id="stopwords", text="Add an optional stopwords: Set<String> parameter (default empty) to countWords that excludes those words from the result, and cover it with a test in WordsTest.kt.",
 partial={"src/Words.kt": ed(W, ("(text: String)", "(text: String, stopwords: Set<String> = emptySet())"), ("        counts[w]", "        if (w in stopwords) continue\n        counts[w]"))},
 done={"src/Words.kt": ed(W, ("(text: String)", "(text: String, stopwords: Set<String> = emptySet())"), ("        counts[w]", "        if (w in stopwords) continue\n        counts[w]")),
       "src/WordsTest.kt": ed(T, ("    }\n}\n", "    }\n\n    @Test\n    fun skipsStopwords() {\n        val c = countWords(\"the cat the dog\", setOf(\"the\"))\n        assertEquals(null, c[\"the\"])\n        assertEquals(1, c[\"cat\"])\n    }\n}\n"))}),
])
