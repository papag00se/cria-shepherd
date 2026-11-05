use csvstats::{mean, parse_column};

#[test]
fn parses_numeric_cells_and_skips_header() {
    let xs = parse_column("a,b\n1,2\n3,x\n5,6\n", 1);
    assert_eq!(xs, vec![2.0, 6.0]);
}

#[test]
fn short_rows_are_ignored() {
    assert_eq!(parse_column("a,b\n1\n2,9\n", 1), vec![9.0]);
}

#[test]
fn mean_of_values() {
    assert_eq!(mean(&[1.0, 2.0, 3.0]), 2.0);
}
