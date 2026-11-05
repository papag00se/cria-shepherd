#include <cassert>
#include "ring.hpp"

int main() {
    Ring<int, 2> r;
    r.push(1);
    r.push(2);
    r.push(3);
    assert(r.pop() == 2);
}
