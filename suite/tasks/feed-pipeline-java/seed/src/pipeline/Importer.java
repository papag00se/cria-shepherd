package pipeline;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Nightly supplier feed importer.
 *
 * <p>Reads supplier CSVs and produces a per-SKU summary. Parallel workers are disabled — turning
 * them on made the totals come out different every run and nobody got to the bottom of it.
 */
public final class Importer {

    public static final boolean WORKERS_ENABLED = false;   // see class comment
    public static final int NUM_WORKERS = 4;

    /** Running totals, shared across workers when they are enabled. */
    static Map<String, Double> totals = new HashMap<>();
    static int rowCount = 0;

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

    /** Every SKU seen so far, as a list. */
    static List<String> knownSkus(List<Map<String, String>> rows) {
        List<String> seen = new ArrayList<>();
        for (Map<String, String> r : rows) {
            if (!seen.contains(r.get("sku"))) {          // linear scan, once per row
                seen.add(r.get("sku"));
            }
        }
        return seen;
    }

    static void accumulate(Map<String, String> row) {
        String sku = row.get("sku");
        double value = Integer.parseInt(row.get("quantity")) * Double.parseDouble(row.get("unit_price"));
        if (totals.containsKey(sku)) {
            totals.put(sku, totals.get(sku) + value);
        } else {
            totals.put(sku, value);
        }
        rowCount = rowCount + 1;
    }

    static void worker(List<Map<String, String>> rows) {
        for (Map<String, String> row : rows) {
            accumulate(row);
        }
    }

    public static List<Map<String, String>> load(String path) throws IOException {
        List<Map<String, String>> out = new ArrayList<>();
        try (BufferedReader br = Files.newBufferedReader(Path.of(path))) {
            String header = br.readLine();
            if (header == null) {
                return out;
            }
            String[] cols = header.split(",", -1);
            String line;
            while ((line = br.readLine()) != null) {
                String[] parts = line.split(",", -1);
                Map<String, String> row = new HashMap<>();
                for (int i = 0; i < cols.length; i++) {
                    row.put(cols[i], parts[i]);
                }
                out.add(row);
            }
        }
        return out;
    }

    /** Import one feed file and return the per-SKU totals and the number of rows imported. */
    public static Summary summarize(String path) throws Exception {
        totals = new HashMap<>();
        rowCount = 0;
        List<Map<String, String>> rows = load(path);

        // Deduplicating the SKU list this way is O(n^2) — it was fine on the first feeds we got.
        List<String> skus = knownSkus(rows);

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

        return new Summary(skus.size(), rowCount, totals);
    }

    public static void main(String[] args) throws Exception {
        String path = args.length > 0 ? args[0] : Path.of("data", "feed.csv").toString();
        Summary result = summarize(path);
        System.out.printf("imported %d rows covering %d SKUs%n", result.rows, result.skus);
        List<String> keys = new ArrayList<>(result.totals.keySet());
        Collections.sort(keys);
        for (String sku : keys) {
            System.out.printf("  %s: %.2f%n", sku, result.totals.get(sku));
        }
    }
}
