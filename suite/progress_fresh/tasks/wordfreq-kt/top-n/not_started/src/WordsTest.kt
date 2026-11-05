import kotlin.test.Test
import kotlin.test.assertEquals

class WordsTest {
    @Test
    fun countsRepeats() {
        assertEquals(2, countWords("a b a")["a"])
    }
}
