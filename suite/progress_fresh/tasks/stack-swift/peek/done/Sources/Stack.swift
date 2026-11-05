struct Stack<T> {
    private var items: [T] = []

    mutating func push(_ x: T) {
        items.append(x)
    }

    mutating func pop() -> T {
        return items.removeLast()
    }

    func peek() -> T? {
        return items.last
    }

    var count: Int { items.count }
}
