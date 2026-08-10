# Feed importer

Reads the nightly supplier CSV and prints a per-SKU summary.

```
mvn -q compile
mvn -q exec:java -Dexec.mainClass=pipeline.Importer -Dexec.args=data/feed.csv
```

Or straight from the compiled classes:

```
java -cp target/classes pipeline.Importer data/feed.csv
```

Parallel workers are switched off. Turning them on changed the totals between runs.
