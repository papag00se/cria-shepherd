use std::io::Read;

fn main() {
    let col: usize = std::env::args().nth(1).and_then(|a| a.parse().ok()).unwrap_or(0);
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let xs = csvstats::parse_column(&input, col);
    println!("mean={} median={}", csvstats::mean(&xs), csvstats::median(&xs));
}
