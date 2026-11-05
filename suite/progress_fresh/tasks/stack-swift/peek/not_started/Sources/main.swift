// drains a small stack
var s = Stack<Int>()
for n in 1...3 { s.push(n) }
while s.count > 0 { print(s.pop()) }
