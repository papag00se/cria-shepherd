import XCTest
@testable import StackLib

final class StackTests: XCTestCase {
    func testPushPop() {
        var s = Stack<Int>()
        s.push(1)
        s.push(2)
        XCTAssertEqual(s.pop(), 2)
    }
}
