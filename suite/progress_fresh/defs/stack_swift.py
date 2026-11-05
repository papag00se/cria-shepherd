from suite.progress_fresh.dsl import ed

SEED = {
"Sources/Stack.swift": '''struct Stack<T> {
    private var items: [T] = []

    mutating func push(_ x: T) {
        items.append(x)
    }

    mutating func pop() -> T {
        return items.removeLast()
    }

    var count: Int { items.count }
}
''',
"Sources/main.swift": '''var s = Stack<Int>()
for n in 1...3 { s.push(n) }
while s.count > 0 { print(s.pop()) }
''',
"Tests/StackTests.swift": '''import XCTest
@testable import StackLib

final class StackTests: XCTestCase {
    func testPushPop() {
        var s = Stack<Int>()
        s.push(1)
        s.push(2)
        XCTAssertEqual(s.pop(), 2)
    }
}
''',
}
S = SEED["Sources/Stack.swift"]
T = SEED["Tests/StackTests.swift"]
POP = ('''    mutating func pop() -> T {
        return items.removeLast()
    }''', '''    mutating func pop() -> T? {
        return items.popLast()
    }''')
PEEK = '''
    func peek() -> T? {
        return items.last
    }
'''
TASK = dict(extension=True, name="stack-swift", language="Swift", seed=SEED,
unrelated={"Sources/main.swift": ed(SEED["Sources/main.swift"], ("var s", "// drains a small stack\nvar s"))},
reqs=[
dict(id="safe-pop", text="pop() crashes on an empty stack. Make it return an optional (nil when empty) and update the callers so nothing force-unwraps an empty pop.",
 partial={"Sources/Stack.swift": ed(S, POP)},
 done={"Sources/Stack.swift": ed(S, POP), "Sources/main.swift": '''var s = Stack<Int>()
for n in 1...3 { s.push(n) }
while let x = s.pop() { print(x) }
'''}),
dict(id="peek", text="Add a non-mutating peek() that returns the top element without removing it (nil when empty), and test both cases.", ns=True,
 partial={"Sources/Stack.swift": ed(S, ("    var count", PEEK.lstrip("\n") + "\n    var count")),
          "Tests/StackTests.swift": ed(T, ("    }\n}\n", "    }\n\n    func testPeekDoesNotRemove() {\n        var s = Stack<Int>()\n        s.push(7)\n        XCTAssertEqual(s.peek(), 7)\n        XCTAssertEqual(s.count, 1)\n    }\n}\n"))},
 done={"Sources/Stack.swift": ed(S, ("    var count", PEEK.lstrip("\n") + "\n    var count")),
       "Tests/StackTests.swift": ed(T, ("    }\n}\n", "    }\n\n    func testPeekDoesNotRemove() {\n        var s = Stack<Int>()\n        s.push(7)\n        XCTAssertEqual(s.peek(), 7)\n        XCTAssertEqual(s.count, 1)\n    }\n\n    func testPeekOnEmptyIsNil() {\n        let s = Stack<Int>()\n        XCTAssertNil(s.peek())\n    }\n}\n"))}),
dict(id="sequence", text="Make Stack conform to Sequence so it can be used in for-in loops, iterating from the top of the stack down without consuming it, and add a test that checks the order.",
 partial={"Sources/Stack.swift": S + "\nextension Stack: Sequence {\n    func makeIterator() -> IndexingIterator<[T]> {\n        return items.makeIterator()\n    }\n}\n"},
 done={"Sources/Stack.swift": S + "\nextension Stack: Sequence {\n    func makeIterator() -> IndexingIterator<[T]> {\n        return items.reversed().makeIterator()\n    }\n}\n",
       "Tests/StackTests.swift": ed(T, ("    }\n}\n", "    }\n\n    func testIteratesTopFirst() {\n        var s = Stack<Int>()\n        s.push(1)\n        s.push(2)\n        s.push(3)\n        XCTAssertEqual(Array(s), [3, 2, 1])\n        XCTAssertEqual(s.count, 3)\n    }\n}\n"))}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["sequence"]["Tests/StackTests.swift"] = ed(T, ("    }\n}\n", "    }\n\n    func testIteratesEverything() {\n        var s = Stack<Int>()\n        s.push(1)\n        s.push(2)\n        XCTAssertEqual(Array(s).count, 2)\n    }\n}\n"))
