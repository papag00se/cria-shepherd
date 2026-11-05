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
    public void RemoveDeletesExisting()
    {
        var r = new Roster();
        r.Add(new Member("Ann", 30));
        Assert.True(r.Remove("Ann"));
        Assert.Empty(r.All());
    }
}
