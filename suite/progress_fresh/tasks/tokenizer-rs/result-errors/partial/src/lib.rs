#[derive(Debug, PartialEq)]
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
            c if c.is_ascii_digit() => {
                let start = i;
                while i + 1 < chars.len() && chars[i + 1].is_ascii_digit() {
                    i += 1;
                }
                let text: String = chars[start..=i].iter().collect();
                out.push(Token::Num(text.parse().unwrap()));
            }
            c if c.is_whitespace() => {}
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
}
