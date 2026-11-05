using System.Collections.Generic;

namespace Team;

public record Member(string Name, int Age);

public class Roster
{
    private readonly List<Member> _members = new();

    public void Add(Member m) => _members.Add(m);

    public bool Remove(string name)
    {
        var m = Find(name);
        return m != null && _members.Remove(m);
    }

    public IReadOnlyList<Member> All() => _members;

    public Member? Find(string name) => _members.Find(m => m.Name == name);
}
