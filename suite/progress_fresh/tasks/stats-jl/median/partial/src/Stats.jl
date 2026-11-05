module Stats

export mean, variance, median

mean(xs) = sum(xs) / length(xs)

function variance(xs)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / length(xs)
end

function median(xs)
    sort!(xs)
    n = length(xs)
    return isodd(n) ? xs[(n + 1) ÷ 2] : (xs[n ÷ 2] + xs[n ÷ 2 + 1]) / 2
end

end
