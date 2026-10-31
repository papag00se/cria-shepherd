package pipeline;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;

/**
 * Nightly supplier feed importer.
 *
 * <p>Reads supplier CSVs and produces a per-SKU summary. Parallel workers are enabled: each worker
 * accumulates its own slice into a private map and count, and the results are merged after the
 * workers finish. Because no shared mutable state is touched while threads run, repeated runs of
 * the same feed always produce identical results.
 *
 * <p>Rows are parsed with Apache Commons CSV so quoted descriptions containing commas are handled
 * correctly. Malformed rows are skipped safely and counted by reason.
 */
public final class Importer {

    public static final boolean WORKERS_ENABLED = true;   // fixed: per-worker local accumulation + merge
    public static final int NUM_WORKERS = 4;

    /** Running totals, shared across workers only for the final merge. */
    private static Map<String, Double> totals = new ConcurrentHashMap<>();
    private static int rowCount = 0;

    /** Per-reason counts of rows skipped during parsing. */
    private static Map<String, Integer> skipCounts = new ConcurrentHashMap<>();

    /** What one import produced. Other tooling reads these three fields by name. */
    public static final class Summary {
        public final int skus;
        public final int rows;
        public final Map<String, Double> totals;

        public Summary(int skus, int rows, Map<String, Double> totals) {
            this.skus = skus;
            this.rows = rows;
            this.totals = totals;
        }
    }

    /** Reasons a data row (excluding the header) may be skipped. */
    public static final class SkipReason {
        public static final String MISSING_COLUMNS = "missing-columns";
        public static final String BAD_QUANTITY = "bad-quantity";
        public static final String BAD_PRICE = "bad-price";
        public static final String MISSING_SKU = "missing-sku";
    }

    /**
     * Load and parse a CSV feed, returning the per-SKU totals and the number of data rows imported.
     *
     * <p>Kept backward compatible: {@code skus}, {@code rows}, and {@code totals} retain their
     * meaning. {@code rows} counts only successfully imported data rows (the header is not counted).
     */
    public static Summary summarize(String path) throws Exception {
        reset();
        List<Map<String, String>> rows = load(path);

        // Collect SKUs in first-seen order using a LinkedHashSet for O(1)
        // membership. The old ArrayList.contains() made this pass O(n^2)
        // (~1.6 billion string comparisons for 40k unique SKUs) and was the
        // dominant cost of the import.
        Set<String> seen = new LinkedHashSet<>();
        for (Map<String, String> r : rows) {
            seen.add(r.get("sku"));
        }
        List<String> skus = new ArrayList<>(seen);

        if (WORKERS_ENABLED) {
            int chunk = Math.max(1, rows.size() / NUM_WORKERS);
            List<Thread> threads = new ArrayList<>();
            for (int i = 0; i < rows.size(); i += chunk) {
                List<Map<String, String>> slice = rows.subList(i, Math.min(i + chunk, rows.size()));
                threads.add(new Thread(() -> worker(slice)));
            }
            for (Thread t : threads) {
                t.start();
            }
            for (Thread t : threads) {
                t.join();
            }
        } else {
            worker(rows);
        }

        return new Summary(skus.size(), rowCount, new LinkedHashMap<>(totals));
    }

    /** Parse one feed file into data rows using a real CSV parser. */
    static List<Map<String, String>> load(String path) throws IOException {
        List<Map<String, String>> out = new ArrayList<>();
        CSVParser parser = CSVFormat.DEFAULT
                .withFirstRecordAsHeader()
                .withTrim(true)
                .builder()
                .build()
                .parse(Files.newBufferedReader(Path.of(path)));

        for (CSVRecord record : parser) {
            Map<String, String> row = parseRecord(record);
            if (row != null) {
                out.add(row);
            }
        }
        return out;
    }

    /**
     * Parse a single CSV record into a row map, or return {@code null} if the row is malformed.
     * Missing columns and quoted descriptions containing commas are handled by the CSV parser;
     * this method validates the parsed fields.
     */
    static Map<String, String> parseRecord(CSVRecord record) {
        // Missing columns: the parser pads short records, but we still guard against it.
        if (record.size() < 4) {
            skip(SkipReason.MISSING_COLUMNS);
            return null;
        }

        String sku = record.get("sku");
        if (sku == null || sku.isEmpty()) {
            skip(SkipReason.MISSING_SKU);
            return null;
        }

        String quantity = record.get("quantity");
        if (quantity == null || quantity.isEmpty()) {
            skip(SkipReason.BAD_QUANTITY);
            return null;
        }
        try {
            Integer.parseInt(quantity);
        } catch (NumberFormatException e) {
            skip(SkipReason.BAD_QUANTITY);
            return null;
        }

        String unitPrice = record.get("unit_price");
        if (unitPrice == null || unitPrice.isEmpty()) {
            skip(SkipReason.BAD_PRICE);
            return null;
        }
        try {
            Double.parseDouble(unitPrice);
        } catch (NumberFormatException e) {
            skip(SkipReason.BAD_PRICE);
            return null;
        }

        // Strip a leading currency symbol if one is present (e.g. "$15.50").
        String cleanPrice = stripCurrency(unitPrice);
        try {
            Double.parseDouble(cleanPrice);
        } catch (NumberFormatException e) {
            skip(SkipReason.BAD_PRICE);
            return null;
        }

        Map<String, String> row = new LinkedHashMap<>();
        row.put("sku", sku);
        row.put("quantity", quantity);
        row.put("unit_price", cleanPrice);
        return row;
    }

    /** Remove a single leading currency symbol from a price string. */
    static String stripCurrency(String price) {
        if (price.length() == 1 && ("$".equals(price) || "%"
                .equals(price) || "#"
                .equals(price) || "@"
                .equals(price))) {
            return "";
        }
        if (price.startsWith("$") || price.startsWith("%") || price.startsWith("#")
                || price.startsWith("@")) {
            return price.substring(1);
        }
        return price;
    }

    /** Accumulate a slice of rows into private local state, then merge into shared state. */
    static void worker(List<Map<String, String>> rows) {
        Map<String, Double> local = new java.util.HashMap<>();
        int localCount = 0;
        for (Map<String, String> row : rows) {
            String sku = row.get("sku");
            double value = Integer.parseInt(row.get("quantity"))
                    * Double.parseDouble(row.get("unit_price"));
            local.merge(sku, value, Double::sum);
            localCount++;
        }
        merge(local, localCount);
    }

    /** Merge per-worker local totals into the shared totals. */
    private static void merge(Map<String, Double> local, int count) {
        for (Map.Entry<String, Double> e : local.entrySet()) {
            totals.merge(e.getKey(), e.getValue(), Double::sum);
        }
        rowCount += count;
    }

    /** Record a skipped row by reason. */
    private static void skip(String reason) {
        skipCounts.merge(reason, 1, Integer::sum);
    }

    private static void reset() {
        totals = new ConcurrentHashMap<>();
        rowCount = 0;
        skipCounts = new ConcurrentHashMap<>();
    }

    public static List<String> knownSkus(List<Map<String, String>> rows) {
        List<String> seen = new ArrayList<>();
        for (Map<String, String> r : rows) {
            if (!seen.contains(r.get("sku"))) {
                seen.add(r.get("sku"));
            }
        }
        return seen;
    }

    public static Map<String, Integer> skippedRows() {
        return new LinkedHashMap<>(skipCounts);
    }

    public static void main(String[] args) throws Exception {
        String path = args.length > 0 ? args[0] : Path.of("data", "feed.csv").toString();
        Summary result = summarize(path);
        System.out.printf("imported %d rows covering %d SKUs%n", result.rows, result.skus);
        List<String> keys = new ArrayList<>(result.totals.keySet());
        java.util.Collections.sort(keys);
        for (String sku : keys) {
            System.out.printf("  %s: %.2f%n", sku, result.totals.get(sku));
        }
        if (!skipCounts.isEmpty()) {
            System.out.println("skipped " + sumValues(skipCounts) + " rows:");
            List<String> reasons = new ArrayList<>(skipCounts.keySet());
            java.util.Collections.sort(reasons);
            for (String reason : reasons) {
                System.out.printf("  %-20s %d%n", reason + ":", skipCounts.get(reason));
            }
        }
    }

    private static int sumValues(Map<String, Integer> m) {
        int total = 0;
        for (int v : m.values()) {
            total += v;
        }
        return total;
    }
}
