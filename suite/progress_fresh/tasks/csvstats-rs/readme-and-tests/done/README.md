# csvstats

    cat data.csv | csvstats 2

Prints the mean and median of column 2 (0-based).

## Output

One line, `mean=<f64> median=<f64>`. The header row is skipped and cells that do not parse as numbers are ignored:

    $ printf 'a,b\n1,2\n3,4\n' | csvstats 1
    mean=3 median=4
