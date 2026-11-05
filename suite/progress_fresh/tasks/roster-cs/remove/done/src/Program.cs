using Team;

var r = new Roster();
r.Add(new Member("Ann", 30));
Console.WriteLine(r.All().Count);
