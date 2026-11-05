module Stats

export mean, variance

mean(xs) = sum(xs) / length(xs)

function variance(xs)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / length(xs)
end

end
