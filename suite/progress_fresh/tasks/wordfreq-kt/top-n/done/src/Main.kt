fun main(args: Array<String>) {
    val top = args.indexOf("--top").let { if (it >= 0) args[it + 1].toInt() else null }
    val rest = if (top != null) args.toList().filterIndexed { i, _ -> i != args.indexOf("--top") && i != args.indexOf("--top") + 1 } else args.toList()
    val text = rest.joinToString(" ")
    val pairs = if (top != null) topWords(text, top) else countWords(text).toList()
    for ((w, c) in pairs) println("$w $c")
}
