module Stats

export mean, variance

mean(xs) = sum(xs) / length(xs)

function variance(xs; corrected::Bool=false)
    corrected && length(xs) < 2 && throw(ArgumentError("need at least two values"))
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / (length(xs) - (corrected ? 1 : 0))
end

end
