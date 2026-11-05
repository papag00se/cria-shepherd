using Test
include("../src/Stats.jl")
using .Stats

@testset "basics" begin
    @test mean([1, 2, 3]) == 2
    @test variance([1, 3]) == 1
end

@testset "empty" begin
    @test_throws ArgumentError mean(Int[])
    @test_throws ArgumentError variance(Float64[])
end
