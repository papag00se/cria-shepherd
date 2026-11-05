TASK = dict(name="ringbuf-cpp", language="C++", seed={
"CMakeLists.txt": 'cmake_minimum_required(VERSION 3.16)\nproject(ringbuf CXX)\nset(CMAKE_CXX_STANDARD 17)\nadd_executable(demo main.cpp)\nenable_testing()\nadd_executable(ring_test ring_test.cpp)\nadd_test(NAME ring_test COMMAND ring_test)\n',
"ring.hpp": '''#pragma once
#include <array>
#include <cstddef>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    std::size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
''',
"main.cpp": '''#include <iostream>
#include "ring.hpp"

int main() {
    Ring<int, 3> r;
    for (int i = 1; i <= 5; ++i) r.push(i);
    while (!r.empty()) std::cout << r.pop() << "\\n";
}
''',
"ring_test.cpp": '''#include <cassert>
#include "ring.hpp"

int main() {
    Ring<int, 2> r;
    r.push(1);
    r.push(2);
    r.push(3);
    assert(r.pop() == 2);
}
''',
}, unrelated={"main.cpp": '''#include <iostream>
#include "ring.hpp"

// prints 3 4 5: the oldest two are overwritten
int main() {
    Ring<int, 3> r;
    for (int i = 1; i <= 5; ++i) r.push(i);
    while (!r.empty()) std::cout << r.pop() << "\\n";
}
'''},
reqs=[
dict(id="pop-empty", text="pop() on an empty ring is undefined behaviour (size_ underflows). Make it throw std::out_of_range and leave the ring unchanged.",
 partial={"ring.hpp": '''#pragma once
#include <array>
#include <cstddef>
#include <stdexcept>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        if (empty()) throw std::out_of_range("ring empty");
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    std::size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
'''},
 done={"ring.hpp": '''#pragma once
#include <array>
#include <cstddef>
#include <stdexcept>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        if (empty()) throw std::out_of_range("Ring::pop on empty ring");
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    std::size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
''', "ring_test.cpp": '''#include <cassert>
#include <stdexcept>
#include "ring.hpp"

int main() {
    Ring<int, 2> r;
    r.push(1);
    r.push(2);
    r.push(3);
    assert(r.pop() == 2);
    assert(r.pop() == 3);
    bool threw = false;
    try {
        r.pop();
    } catch (const std::out_of_range&) {
        threw = true;
    }
    assert(threw && r.size() == 0);
}
'''}),
dict(id="peek-and-full", text="Add `const T& front() const` (throws std::out_of_range when empty) and `bool full() const` to Ring, without removing anything.",
 partial={"ring.hpp": '''#pragma once
#include <array>
#include <cstddef>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    const T& front() const { return data_[head_]; }

    std::size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
'''},
 done={"ring.hpp": '''#pragma once
#include <array>
#include <cstddef>
#include <stdexcept>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    const T& front() const {
        if (empty()) throw std::out_of_range("Ring::front on empty ring");
        return data_[head_];
    }

    std::size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }
    bool full() const { return size_ == N; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
'''}),
dict(id="capacity-doc", text="Document the overwrite-oldest behaviour: add a README.md that explains Ring<T, N> (fixed capacity, push overwrites the oldest element when full) with a short usage example, and add a capacity() accessor returning N.",
 partial={"README.md": "# ringbuf\n\nA fixed-capacity ring buffer, `Ring<T, N>`.\n\n    Ring<int, 3> r;\n    r.push(1);\n    int x = r.pop();\n"},
 done={"README.md": "# ringbuf\n\nA fixed-capacity ring buffer, `Ring<T, N>`.\n\n`push` overwrites the oldest element when the ring is full; `pop` removes the oldest. `capacity()` returns N.\n\n    Ring<int, 3> r;\n    for (int i = 1; i <= 5; ++i) r.push(i);  // keeps 3, 4, 5\n    int oldest = r.pop();                   // 3\n", "ring.hpp": '''#pragma once
#include <array>
#include <cstddef>

template <typename T, std::size_t N>
class Ring {
public:
    void push(const T& v) {
        data_[(head_ + size_) % N] = v;
        if (size_ < N) {
            ++size_;
        } else {
            head_ = (head_ + 1) % N;
        }
    }

    T pop() {
        T v = data_[head_];
        head_ = (head_ + 1) % N;
        --size_;
        return v;
    }

    std::size_t size() const { return size_; }
    constexpr std::size_t capacity() const { return N; }
    bool empty() const { return size_ == 0; }

private:
    std::array<T, N> data_{};
    std::size_t head_ = 0;
    std::size_t size_ = 0;
};
'''}),
])
