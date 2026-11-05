#include <cassert>
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
