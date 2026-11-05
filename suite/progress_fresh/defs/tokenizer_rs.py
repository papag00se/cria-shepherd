from suite.progress_fresh.dsl import ed

SEED = {
"Cargo.toml": '[package]\nname = "tok"\nversion = "0.1.0"\nedition = "2021"\n',
"src/lib.rs": '''#[derive(Debug, PartialEq)]
pub enum Token {
    Num(f64),
    Plus,
    Minus,
    Star,
}

pub fn tokenize(s: &str) -> Vec<Token> {
    let mut out = Vec::new();
    let chars: Vec<char> = s.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        match c {
            '+' => out.push(Token::Plus),
            '-' => out.push(Token::Minus),
            '*' => out.push(Token::Star),
            c if c.is_ascii_digit() => {
                let start = i;
                while i + 1 < chars.len() && chars[i + 1].is_ascii_digit() {
                    i += 1;
                }
                let text: String = chars[start..=i].iter().collect();
                out.push(Token::Num(text.parse().unwrap()));
            }
            _ => {}
        }
        i += 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simple_sum() {
        assert_eq!(tokenize("1+2"), vec![Token::Num(1.0), Token::Plus, Token::Num(2.0)]);
    }
}
''',
"src/main.rs": 'fn main() {\n    let line = std::env::args().nth(1).unwrap_or_default();\n    println!("{:?}", tok::tokenize(&line));\n}\n',
}
L = SEED["src/lib.rs"]
M = SEED["src/main.rs"]
DEC_OLD = '''                while i + 1 < chars.len() && chars[i + 1].is_ascii_digit() {'''
DEC_NEW = '''                while i + 1 < chars.len() && (chars[i + 1].is_ascii_digit() || chars[i + 1] == '.') {'''
TASK = dict(extension=True, name="tokenizer-rs", language="Rust", seed=SEED,
unrelated={"Cargo.toml": SEED["Cargo.toml"] + 'description = "arithmetic tokenizer"\n'},
reqs=[
dict(id="decimals", text="Numbers with a decimal point such as \"3.14\" are split into two numbers and a dropped '.'. Make tokenize read decimals as a single Num and add a test.",
 partial={"src/lib.rs": ed(L, (DEC_OLD, DEC_NEW))},
 done={"src/lib.rs": ed(L, (DEC_OLD, DEC_NEW), ("    }\n}\n", "    }\n\n    #[test]\n    fn decimals() {\n        assert_eq!(tokenize(\"3.14*2\"), vec![Token::Num(3.14), Token::Star, Token::Num(2.0)]);\n    }\n}\n"))}),
dict(id="result-errors", text="tokenize silently drops unknown characters and panics on a malformed number like \"1.2.3\". Return Result<Vec<Token>, TokenError> with the offending character/position, skip only whitespace, update main, and test an unexpected character.",
 partial={"src/lib.rs": ed(L, ("pub fn tokenize(s: &str) -> Vec<Token> {", "#[derive(Debug, PartialEq)]\npub struct TokenError {\n    pub pos: usize,\n    pub ch: char,\n}\n\npub fn tokenize(s: &str) -> Result<Vec<Token>, TokenError> {"), ("            _ => {}", "            c if c.is_whitespace() => {}\n            c => return Err(TokenError { pos: i, ch: c }),"), ("    out\n}", "    Ok(out)\n}"), ("assert_eq!(tokenize(\"1+2\"), vec![Token::Num(1.0), Token::Plus, Token::Num(2.0)]);", "assert_eq!(tokenize(\"1+2\").unwrap(), vec![Token::Num(1.0), Token::Plus, Token::Num(2.0)]);"))},
 done={"src/lib.rs": '''#[derive(Debug, PartialEq)]
pub enum Token {
    Num(f64),
    Plus,
    Minus,
    Star,
}

#[derive(Debug, PartialEq)]
pub struct TokenError {
    pub pos: usize,
    pub ch: char,
}

pub fn tokenize(s: &str) -> Result<Vec<Token>, TokenError> {
    let mut out = Vec::new();
    let chars: Vec<char> = s.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        match c {
            '+' => out.push(Token::Plus),
            '-' => out.push(Token::Minus),
            '*' => out.push(Token::Star),
            c if c.is_whitespace() => {}
            c if c.is_ascii_digit() => {
                let start = i;
                while i + 1 < chars.len() && chars[i + 1].is_ascii_digit() {
                    i += 1;
                }
                let text: String = chars[start..=i].iter().collect();
                out.push(Token::Num(text.parse().unwrap()));
            }
            c => return Err(TokenError { pos: i, ch: c }),
        }
        i += 1;
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simple_sum() {
        assert_eq!(tokenize("1+2").unwrap(), vec![Token::Num(1.0), Token::Plus, Token::Num(2.0)]);
    }

    #[test]
    fn unexpected_character_is_reported() {
        assert_eq!(tokenize("1 + x"), Err(TokenError { pos: 4, ch: 'x' }));
    }

    #[test]
    fn whitespace_is_skipped() {
        assert_eq!(tokenize(" 7 ").unwrap(), vec![Token::Num(7.0)]);
    }
}
''', "src/main.rs": 'fn main() {\n    let line = std::env::args().nth(1).unwrap_or_default();\n    match tok::tokenize(&line) {\n        Ok(toks) => println!("{:?}", toks),\n        Err(e) => eprintln!("unexpected {:?} at {}", e.ch, e.pos),\n    }\n}\n'}),
dict(id="slash-parens", text="Add Slash, LParen and RParen tokens recognised by tokenize and cover each in a test.",
 partial={"src/lib.rs": ed(L, ("    Star,\n}", "    Star,\n    Slash,\n    LParen,\n    RParen,\n}"), ("            '*' => out.push(Token::Star),\n", "            '*' => out.push(Token::Star),\n            '/' => out.push(Token::Slash),\n            '(' => out.push(Token::LParen),\n"))},
 done={"src/lib.rs": ed(L, ("    Star,\n}", "    Star,\n    Slash,\n    LParen,\n    RParen,\n}"), ("            '*' => out.push(Token::Star),\n", "            '*' => out.push(Token::Star),\n            '/' => out.push(Token::Slash),\n            '(' => out.push(Token::LParen),\n            ')' => out.push(Token::RParen),\n"), ("    }\n}\n", "    }\n\n    #[test]\n    fn grouping_and_division() {\n        assert_eq!(\n            tokenize(\"(8/2)\"),\n            vec![Token::LParen, Token::Num(8.0), Token::Slash, Token::Num(2.0), Token::RParen]\n        );\n    }\n}\n"))}),
])
