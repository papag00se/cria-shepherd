from suite.progress_fresh.dsl import ed

SEED = {
"src/Roster.cs": '''using System.Collections.Generic;

namespace Team;

public record Member(string Name, int Age);

public class Roster
{
    private readonly List<Member> _members = new();

    public void Add(Member m) => _members.Add(m);

    public IReadOnlyList<Member> All() => _members;

    public Member? Find(string name) => _members.Find(m => m.Name == name);
}
''',
"tests/RosterTests.cs": '''using Team;
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
}
''',
"src/Program.cs": '''using Team;

var r = new Roster();
r.Add(new Member("Ann", 30));
Console.WriteLine(r.All().Count);
''',
}
R = SEED["src/Roster.cs"]
T = SEED["tests/RosterTests.cs"]
P = SEED["src/Program.cs"]
TASK = dict(extension=True, name="roster-cs", language="C#", seed=SEED,
unrelated={"src/Program.cs": "// quick smoke run\n" + P},
reqs=[
dict(id="no-duplicates", text="Add must reject a member whose name already exists (case-insensitive) by throwing InvalidOperationException, and a test must cover the duplicate case.",
 partial={"src/Roster.cs": ed(R, ("    public void Add(Member m) => _members.Add(m);", "    public void Add(Member m)\n    {\n        if (_members.Exists(x => x.Name == m.Name))\n            throw new InvalidOperationException(\"duplicate\");\n        _members.Add(m);\n    }")),
          "tests/RosterTests.cs": T},
 done={"src/Roster.cs": ed(R, ("using System.Collections.Generic;", "using System;\nusing System.Collections.Generic;"), ("    public void Add(Member m) => _members.Add(m);", "    public void Add(Member m)\n    {\n        if (_members.Exists(x => string.Equals(x.Name, m.Name, StringComparison.OrdinalIgnoreCase)))\n            throw new InvalidOperationException($\"duplicate member: {m.Name}\");\n        _members.Add(m);\n    }")),
       "tests/RosterTests.cs": ed(T, ("using Team;", "using System;\nusing Team;"), ("    }\n}\n", "    }\n\n    [Fact]\n    public void RejectsDuplicateNamesIgnoringCase()\n    {\n        var r = new Roster();\n        r.Add(new Member(\"Ann\", 30));\n        Assert.Throws<InvalidOperationException>(() => r.Add(new Member(\"ann\", 41)));\n        Assert.Single(r.All());\n    }\n}\n"))}),
dict(id="remove", text="Add bool Remove(string name) that deletes the member and returns true, or false when nobody has that name; cover both outcomes in RosterTests.",
 partial={"src/Roster.cs": ed(R, ("    public IReadOnlyList", "    public bool Remove(string name)\n    {\n        var m = Find(name);\n        _members.Remove(m!);\n        return true;\n    }\n\n    public IReadOnlyList"))},
 done={"src/Roster.cs": ed(R, ("    public IReadOnlyList", "    public bool Remove(string name)\n    {\n        var m = Find(name);\n        return m != null && _members.Remove(m);\n    }\n\n    public IReadOnlyList")),
       "tests/RosterTests.cs": ed(T, ("    }\n}\n", "    }\n\n    [Fact]\n    public void RemoveReportsWhetherItDeleted()\n    {\n        var r = new Roster();\n        r.Add(new Member(\"Ann\", 30));\n        Assert.True(r.Remove(\"Ann\"));\n        Assert.False(r.Remove(\"Ann\"));\n        Assert.Empty(r.All());\n    }\n}\n"))}),
dict(id="oldest", text="Add Oldest() returning the member with the greatest Age (first added wins ties) or null for an empty roster, and print the oldest member's name in Program.cs.",
 partial={"src/Roster.cs": ed(R, ("    public Member? Find", "    public Member? Oldest()\n    {\n        Member? best = null;\n        foreach (var m in _members)\n            if (best == null || m.Age > best.Age) best = m;\n        return best;\n    }\n\n    public Member? Find"))},
 done={"src/Roster.cs": ed(R, ("    public Member? Find", "    public Member? Oldest()\n    {\n        Member? best = null;\n        foreach (var m in _members)\n            if (best == null || m.Age > best.Age) best = m;\n        return best;\n    }\n\n    public Member? Find")),
       "src/Program.cs": P + "Console.WriteLine(r.Oldest()?.Name ?? \"nobody\");\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["no-duplicates"]["tests/RosterTests.cs"] = ed(T, ("using Team;", "using System;\nusing Team;"), ("    }\n}\n", "    }\n\n    [Fact]\n    public void RejectsExactDuplicate()\n    {\n        var r = new Roster();\n        r.Add(new Member(\"Ann\", 30));\n        Assert.Throws<InvalidOperationException>(() => r.Add(new Member(\"Ann\", 41)));\n    }\n}\n"))
_P["remove"]["tests/RosterTests.cs"] = ed(T, ("    }\n}\n", "    }\n\n    [Fact]\n    public void RemoveDeletesExisting()\n    {\n        var r = new Roster();\n        r.Add(new Member(\"Ann\", 30));\n        Assert.True(r.Remove(\"Ann\"));\n        Assert.Empty(r.All());\n    }\n}\n"))
