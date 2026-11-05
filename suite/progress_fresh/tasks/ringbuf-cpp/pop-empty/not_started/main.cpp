#include <iostream>
#include "ring.hpp"

int main() {
    Ring<int, 3> r;
    for (int i = 1; i <= 5; ++i) r.push(i);
    while (!r.empty()) std::cout << r.pop() << "\n";
}
