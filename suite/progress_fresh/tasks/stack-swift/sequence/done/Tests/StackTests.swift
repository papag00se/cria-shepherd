import XCTest
@testable import StackLib

final class StackTests: XCTestCase {
    func testPushPop() {
        var s = Stack<Int>()
        s.push(1)
        s.push(2)
        XCTAssertEqual(s.pop(), 2)
    }

    func testIteratesTopFirst() {
        var s = Stack<Int>()
        s.push(1)
        s.push(2)
        s.push(3)
        XCTAssertEqual(Array(s), [3, 2, 1])
        XCTAssertEqual(s.count, 3)
    }
}
