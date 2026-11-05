TASK = dict(name="csvstats-rs", language="Rust", seed={
"Cargo.toml": '[package]\nname = "csvstats"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
"src/lib.rs": '''pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
    input
        .lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(col))
        .filter_map(|c| c.trim().parse().ok())
        .collect()
}

pub fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

pub fn median(xs: &[f64]) -> f64 {
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[v.len() / 2]
}
''',
"src/main.rs": '''use std::io::Read;

fn main() {
    let col: usize = std::env::args().nth(1).and_then(|a| a.parse().ok()).unwrap_or(0);
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let xs = csvstats::parse_column(&input, col);
    println!("mean={} median={}", csvstats::mean(&xs), csvstats::median(&xs));
}
''',
"README.md": "# csvstats\n\n    cat data.csv | csvstats 2\n\nPrints the mean and median of column 2 (0-based).\n",
}, unrelated={"README.md": "# csvstats\n\n    cat data.csv | csvstats 2\n\nPrints the mean and median of the given column (0-based).\n"},
reqs=[
dict(id="median-even", text="median() is wrong for even-length input (it returns the upper middle element) and panics on empty input. Make it average the two middle values and return None for an empty slice, updating callers.",
 partial={"src/lib.rs": '''pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
    input
        .lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(col))
        .filter_map(|c| c.trim().parse().ok())
        .collect()
}

pub fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

pub fn median(xs: &[f64]) -> Option<f64> {
    if xs.is_empty() {
        return None;
    }
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    Some(v[v.len() / 2])
}
'''},
 done={"src/lib.rs": '''pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
    input
        .lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(col))
        .filter_map(|c| c.trim().parse().ok())
        .collect()
}

pub fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

pub fn median(xs: &[f64]) -> Option<f64> {
    if xs.is_empty() {
        return None;
    }
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mid = v.len() / 2;
    Some(if v.len() % 2 == 0 { (v[mid - 1] + v[mid]) / 2.0 } else { v[mid] })
}
''', "src/main.rs": '''use std::io::Read;

fn main() {
    let col: usize = std::env::args().nth(1).and_then(|a| a.parse().ok()).unwrap_or(0);
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let xs = csvstats::parse_column(&input, col);
    match csvstats::median(&xs) {
        Some(m) => println!("mean={} median={}", csvstats::mean(&xs), m),
        None => {
            eprintln!("no numeric values in column {col}");
            std::process::exit(1);
        }
    }
}
'''}),
dict(id="stddev", text="Add a population standard deviation function `stddev(xs: &[f64]) -> f64` to the library and print it as a third `stddev=` field in the CLI output.",
 partial={"src/lib.rs": '''pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
    input
        .lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(col))
        .filter_map(|c| c.trim().parse().ok())
        .collect()
}

pub fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

pub fn median(xs: &[f64]) -> f64 {
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[v.len() / 2]
}

pub fn stddev(xs: &[f64]) -> f64 {
    let m = mean(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / xs.len() as f64).sqrt()
}
'''},
 done={"src/lib.rs": '''pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
    input
        .lines()
        .skip(1)
        .filter_map(|l| l.split(',').nth(col))
        .filter_map(|c| c.trim().parse().ok())
        .collect()
}

pub fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

pub fn median(xs: &[f64]) -> f64 {
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[v.len() / 2]
}

/// Population standard deviation.
pub fn stddev(xs: &[f64]) -> f64 {
    let m = mean(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / xs.len() as f64).sqrt()
}
''', "src/main.rs": '''use std::io::Read;

fn main() {
    let col: usize = std::env::args().nth(1).and_then(|a| a.parse().ok()).unwrap_or(0);
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let xs = csvstats::parse_column(&input, col);
    println!(
        "mean={} median={} stddev={}",
        csvstats::mean(&xs),
        csvstats::median(&xs),
        csvstats::stddev(&xs)
    );
}
'''}),
dict(id="readme-and-tests", text="Add integration tests in tests/stats.rs covering parse_column (header skipped, bad cells ignored) and mean, and document the output format with an example in the README.",
 partial={"tests/stats.rs": '''use csvstats::{mean, parse_column};

#[test]
fn parses_numeric_cells() {
    let xs = parse_column("a,b\\n1,2\\n3,x\\n5,6\\n", 1);
    assert_eq!(xs, vec![2.0, 6.0]);
}

#[test]
fn mean_of_values() {
    assert_eq!(mean(&[1.0, 2.0, 3.0]), 2.0);
}
'''},
 done={"tests/stats.rs": '''use csvstats::{mean, parse_column};

#[test]
fn parses_numeric_cells_and_skips_header() {
    let xs = parse_column("a,b\\n1,2\\n3,x\\n5,6\\n", 1);
    assert_eq!(xs, vec![2.0, 6.0]);
}

#[test]
fn short_rows_are_ignored() {
    assert_eq!(parse_column("a,b\\n1\\n2,9\\n", 1), vec![9.0]);
}

#[test]
fn mean_of_values() {
    assert_eq!(mean(&[1.0, 2.0, 3.0]), 2.0);
}
''', "README.md": "# csvstats\n\n    cat data.csv | csvstats 2\n\nPrints the mean and median of column 2 (0-based).\n\n## Output\n\nOne line, `mean=<f64> median=<f64>`. The header row is skipped and cells that do not parse as numbers are ignored:\n\n    $ printf 'a,b\\n1,2\\n3,4\\n' | csvstats 1\n    mean=3 median=4\n"}),
])
