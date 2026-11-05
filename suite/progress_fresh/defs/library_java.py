TASK = dict(name="library-java", language="Java", seed={
"pom.xml": '''<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>example</groupId>
  <artifactId>library</artifactId>
  <version>0.1.0</version>
  <properties><maven.compiler.release>17</maven.compiler.release></properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
''',
"src/main/java/library/Library.java": '''package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        dueDates.put(isbn, today.plusDays(14));
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        return (today.toEpochDay() - due.toEpochDay()) * 25;
    }
}
''',
"src/test/java/library/LibraryTest.java": '''package library;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LibraryTest {
    @Test
    void noFineWhenOnTime() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 1, 15)));
    }
}
''',
}, unrelated={"src/test/java/library/LibraryTest.java": '''package library;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LibraryTest {
    @Test
    void noFineWhenOnTime() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 1, 15)));
    }
    // TODO more cases
}
'''},
reqs=[
dict(id="double-checkout", text="checkout() must refuse a book that is already checked out: throw IllegalStateException and leave the original due date unchanged.",
 partial={"src/main/java/library/Library.java": '''package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        if (dueDates.containsKey(isbn)) {
            throw new IllegalStateException("already checked out: " + isbn);
        }
        dueDates.put(isbn, today.plusDays(14));
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        return (today.toEpochDay() - due.toEpochDay()) * 25;
    }
}
'''},
 done={"src/main/java/library/Library.java": '''package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        if (dueDates.putIfAbsent(isbn, today.plusDays(14)) != null) {
            throw new IllegalStateException("already checked out: " + isbn);
        }
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        return (today.toEpochDay() - due.toEpochDay()) * 25;
    }
}
'''}),
dict(id="fine-cap", text="Cap a single loan's fine at 1000 cents (a constant MAX_FINE_CENTS), and keep charging 25 cents per late day below the cap.",
 partial={"src/main/java/library/Library.java": '''package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    private static final long MAX_FINE_CENTS = 1000;
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        dueDates.put(isbn, today.plusDays(14));
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        return (today.toEpochDay() - due.toEpochDay()) * 25;
    }
}
'''},
 done={"src/main/java/library/Library.java": '''package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    static final long MAX_FINE_CENTS = 1000;
    private static final long DAILY_FINE_CENTS = 25;
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        dueDates.put(isbn, today.plusDays(14));
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        long days = today.toEpochDay() - due.toEpochDay();
        return Math.min(days * DAILY_FINE_CENTS, MAX_FINE_CENTS);
    }
}
'''}),
dict(id="late-tests", text="Add JUnit tests to LibraryTest for: a fine of exactly 25 cents one day late, a fine for a book that was never checked out (0), and no fine after giveBack.",
 partial={"src/test/java/library/LibraryTest.java": '''package library;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LibraryTest {
    @Test
    void noFineWhenOnTime() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 1, 15)));
    }

    @Test
    void oneDayLateIs25Cents() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(25, l.fineCents("1", LocalDate.of(2024, 1, 16)));
    }
}
'''},
 done={"src/test/java/library/LibraryTest.java": '''package library;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LibraryTest {
    @Test
    void noFineWhenOnTime() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 1, 15)));
    }

    @Test
    void oneDayLateIs25Cents() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(25, l.fineCents("1", LocalDate.of(2024, 1, 16)));
    }

    @Test
    void neverCheckedOutIsZero() {
        assertEquals(0, new Library().fineCents("9", LocalDate.of(2024, 6, 1)));
    }

    @Test
    void noFineAfterGiveBack() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        l.giveBack("1");
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 3, 1)));
    }
}
'''}),
])
