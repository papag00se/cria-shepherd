fun main(args: Array<String>) {
    val top = args.indexOf("--top").let { if (it >= 0) args[it + 1].toInt() else null }
    val text = args.joinToString(" ")
    val pairs = if (top != null) topWords(text, top) else countWords(text).toList()
    for ((w, c) in pairs) println("$w $c")
}
