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

pub fn median(xs: &[f64]) -> f64 {
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[v.len() / 2]
}

pub fn stddev(xs: &[f64]) -> f64 {
    let m = mean(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / xs.len() as f64).sqrt()
}
