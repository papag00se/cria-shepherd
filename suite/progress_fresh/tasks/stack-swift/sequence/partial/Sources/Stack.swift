struct Stack<T> {
    private var items: [T] = []

    mutating func push(_ x: T) {
        items.append(x)
    }

    mutating func pop() -> T {
        return items.removeLast()
    }

    var count: Int { items.count }
}

extension Stack: Sequence {
    func makeIterator() -> IndexingIterator<[T]> {
        return items.makeIterator()
    }
}
