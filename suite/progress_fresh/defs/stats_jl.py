from suite.progress_fresh.dsl import ed

SEED = {
"src/Stats.jl": '''module Stats

export mean, variance

mean(xs) = sum(xs) / length(xs)

function variance(xs)
    m = mean(xs)
    return sum((x - m)^2 for x in xs) / length(xs)
end

end
''',
"test/runtests.jl": '''using Test
include("../src/Stats.jl")
using .Stats

@testset "basics" begin
    @test mean([1, 2, 3]) == 2
    @test variance([1, 3]) == 1
end
''',
}
S = SEED["src/Stats.jl"]
T = SEED["test/runtests.jl"]
TASK = dict(extension=True, name="stats-jl", language="Julia", seed=SEED,
unrelated={"src/Stats.jl": ed(S, ("mean(xs) =", "# arithmetic mean\nmean(xs) ="))},
reqs=[
dict(id="empty", text="mean and variance of an empty collection currently return NaN or throw a cryptic error. Make both throw ArgumentError(\"empty collection\") explicitly and test it.",
 partial={"src/Stats.jl": ed(S, ("mean(xs) = sum(xs) / length(xs)", "function mean(xs)\n    isempty(xs) && throw(ArgumentError(\"empty collection\"))\n    return sum(xs) / length(xs)\nend"))},
 done={"src/Stats.jl": ed(S, ("mean(xs) = sum(xs) / length(xs)", "function mean(xs)\n    isempty(xs) && throw(ArgumentError(\"empty collection\"))\n    return sum(xs) / length(xs)\nend")),
       "test/runtests.jl": T + "\n@testset \"empty\" begin\n    @test_throws ArgumentError mean(Int[])\n    @test_throws ArgumentError variance(Float64[])\nend\n"}),
dict(id="sample-variance", text="Add a keyword argument corrected::Bool=false to variance so corrected=true divides by n-1 (sample variance); it must throw ArgumentError when corrected is true and there is only one element.",
 partial={"src/Stats.jl": ed(S, ("function variance(xs)", "function variance(xs; corrected::Bool=false)"), ("/ length(xs)\nend", "/ (length(xs) - (corrected ? 1 : 0))\nend"))},
 done={"src/Stats.jl": ed(S, ("function variance(xs)", "function variance(xs; corrected::Bool=false)\n    corrected && length(xs) < 2 && throw(ArgumentError(\"need at least two values\"))"), ("/ length(xs)\nend", "/ (length(xs) - (corrected ? 1 : 0))\nend")),
       "test/runtests.jl": T + "\n@testset \"sample variance\" begin\n    @test variance([1, 3]; corrected=true) == 2\n    @test_throws ArgumentError variance([5]; corrected=true)\nend\n"}),
dict(id="median", text="Export a median function that handles odd and even lengths (average of the middle two), does not mutate its argument, and is covered by tests for both parities and for non-mutation.",
 partial={"src/Stats.jl": ed(S, ("export mean, variance", "export mean, variance, median"), ("end\n\nend\n", "end\n\nfunction median(xs)\n    sort!(xs)\n    n = length(xs)\n    return isodd(n) ? xs[(n + 1) ÷ 2] : (xs[n ÷ 2] + xs[n ÷ 2 + 1]) / 2\nend\n\nend\n")),
          "test/runtests.jl": T + "\n@testset \"median\" begin\n    @test median([3, 1, 2]) == 2\nend\n"},
 done={"src/Stats.jl": ed(S, ("export mean, variance", "export mean, variance, median"), ("end\n\nend\n", "end\n\nfunction median(xs)\n    s = sort(xs)\n    n = length(s)\n    return isodd(n) ? s[(n + 1) ÷ 2] : (s[n ÷ 2] + s[n ÷ 2 + 1]) / 2\nend\n\nend\n")),
       "test/runtests.jl": T + "\n@testset \"median\" begin\n    @test median([3, 1, 2]) == 2\n    @test median([4, 1, 3, 2]) == 2.5\n    xs = [3, 1, 2]\n    median(xs)\n    @test xs == [3, 1, 2]\nend\n"}),
])
