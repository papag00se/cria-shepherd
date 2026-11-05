package library;

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
