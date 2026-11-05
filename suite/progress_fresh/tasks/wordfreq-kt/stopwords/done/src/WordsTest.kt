import kotlin.test.Test
import kotlin.test.assertEquals

class WordsTest {
    @Test
    fun countsRepeats() {
        assertEquals(2, countWords("a b a")["a"])
    }

    @Test
    fun skipsStopwords() {
        val c = countWords("the cat the dog", setOf("the"))
        assertEquals(null, c["the"])
        assertEquals(1, c["cat"])
    }
}
