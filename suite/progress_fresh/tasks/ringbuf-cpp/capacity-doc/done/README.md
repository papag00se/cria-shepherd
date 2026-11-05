# ringbuf

A fixed-capacity ring buffer, `Ring<T, N>`.

`push` overwrites the oldest element when the ring is full; `pop` removes the oldest. `capacity()` returns N.

    Ring<int, 3> r;
    for (int i = 1; i <= 5; ++i) r.push(i);  // keeps 3, 4, 5
    int oldest = r.pop();                   // 3
