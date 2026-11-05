#pragma once
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
