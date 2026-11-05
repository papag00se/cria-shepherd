pub fn parse_column(input: &str, col: usize) -> Vec<f64> {
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
