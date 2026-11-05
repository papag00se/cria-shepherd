using System;
using System.Collections.Generic;

namespace Team;

public record Member(string Name, int Age);

public class Roster
{
    private readonly List<Member> _members = new();

    public void Add(Member m)
    {
        if (_members.Exists(x => string.Equals(x.Name, m.Name, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException($"duplicate member: {m.Name}");
        _members.Add(m);
    }

    public IReadOnlyList<Member> All() => _members;

    public Member? Find(string name) => _members.Find(m => m.Name == name);
}
