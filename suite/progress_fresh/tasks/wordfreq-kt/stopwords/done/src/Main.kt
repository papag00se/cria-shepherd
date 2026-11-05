fun main(args: Array<String>) {
    val text = args.joinToString(" ")
    for ((w, c) in countWords(text)) println("$w $c")
}
