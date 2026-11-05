using System.Collections.Generic;

namespace Team;

public record Member(string Name, int Age);

public class Roster
{
    private readonly List<Member> _members = new();

    public void Add(Member m) => _members.Add(m);

    public IReadOnlyList<Member> All() => _members;

    public Member? Oldest()
    {
        Member? best = null;
        foreach (var m in _members)
            if (best == null || m.Age > best.Age) best = m;
        return best;
    }

    public Member? Find(string name) => _members.Find(m => m.Name == name);
}
