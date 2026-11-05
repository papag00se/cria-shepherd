#[derive(Debug, PartialEq)]
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
                while i + 1 < chars.len() && (chars[i + 1].is_ascii_digit() || chars[i + 1] == '.') {
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
