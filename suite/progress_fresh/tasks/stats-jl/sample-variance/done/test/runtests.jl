using Test
include("../src/Stats.jl")
using .Stats

@testset "basics" begin
    @test mean([1, 2, 3]) == 2
    @test variance([1, 3]) == 1
end

@testset "sample variance" begin
    @test variance([1, 3]; corrected=true) == 2
    @test_throws ArgumentError variance([5]; corrected=true)
end
