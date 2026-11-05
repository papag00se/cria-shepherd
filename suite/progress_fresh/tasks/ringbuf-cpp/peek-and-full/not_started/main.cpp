#include <iostream>
#include "ring.hpp"

// prints 3 4 5: the oldest two are overwritten
int main() {
    Ring<int, 3> r;
    for (int i = 1; i <= 5; ++i) r.push(i);
    while (!r.empty()) std::cout << r.pop() << "\n";
}
