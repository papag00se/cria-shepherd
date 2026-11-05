fn main() {
    let line = std::env::args().nth(1).unwrap_or_default();
    println!("{:?}", tok::tokenize(&line));
}
