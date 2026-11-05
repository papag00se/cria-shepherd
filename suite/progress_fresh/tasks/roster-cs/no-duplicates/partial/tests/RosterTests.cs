using System;
using Team;
using Xunit;

public class RosterTests
{
    [Fact]
    public void AddsMembers()
    {
        var r = new Roster();
        r.Add(new Member("Ann", 30));
        Assert.Single(r.All());
    }

    [Fact]
    public void RejectsExactDuplicate()
    {
        var r = new Roster();
        r.Add(new Member("Ann", 30));
        Assert.Throws<InvalidOperationException>(() => r.Add(new Member("Ann", 41)));
    }
}
