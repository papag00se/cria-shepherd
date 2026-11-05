fn main() {
    let line = std::env::args().nth(1).unwrap_or_default();
    match tok::tokenize(&line) {
        Ok(toks) => println!("{:?}", toks),
        Err(e) => eprintln!("unexpected {:?} at {}", e.ch, e.pos),
    }
}
