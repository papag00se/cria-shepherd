// prints one "word count" pair per line
fun main(args: Array<String>) {
    val text = args.joinToString(" ")
    for ((w, c) in countWords(text)) println("$w $c")
}
