# ringbuf

A fixed-capacity ring buffer, `Ring<T, N>`.

    Ring<int, 3> r;
    r.push(1);
    int x = r.pop();
