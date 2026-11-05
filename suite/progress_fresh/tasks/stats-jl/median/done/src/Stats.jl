module Stats

export mean, variance, median

mean(xs) = sum(xs) / length(xs)

function variance(xs)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / length(xs)
end

function median(xs)
    s = sort(xs)
    n = length(s)
    return isodd(n) ? s[(n + 1) ÷ 2] : (s[n ÷ 2] + s[n ÷ 2 + 1]) / 2
end

end
