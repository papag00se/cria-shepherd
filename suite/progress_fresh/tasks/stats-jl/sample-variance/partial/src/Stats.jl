module Stats

export mean, variance

mean(xs) = sum(xs) / length(xs)

function variance(xs; corrected::Bool=false)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / (length(xs) - (corrected ? 1 : 0))
end

end
