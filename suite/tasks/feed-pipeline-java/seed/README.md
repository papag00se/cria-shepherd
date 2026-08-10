# Feed importer

Reads the nightly supplier CSV and prints a per-SKU summary.

```
javac -d out $(find src -name '*.java')
java -cp out pipeline.Importer data/feed.csv
```

Parallel workers are switched off. Turning them on changed the totals between runs.
