module Stats

export mean, variance

function mean(xs)
    isempty(xs) && throw(ArgumentError("empty collection"))
    return sum(xs) / length(xs)
end

function variance(xs)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / length(xs)
end

end
