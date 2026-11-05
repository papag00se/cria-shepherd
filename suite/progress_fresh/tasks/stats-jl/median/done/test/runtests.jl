using Test
include("../src/Stats.jl")
using .Stats

@testset "basics" begin
    @test mean([1, 2, 3]) == 2
    @test variance([1, 3]) == 1
end

@testset "median" begin
    @test median([3, 1, 2]) == 2
    @test median([4, 1, 3, 2]) == 2.5
    xs = [3, 1, 2]
    median(xs)
    @test xs == [3, 1, 2]
end
