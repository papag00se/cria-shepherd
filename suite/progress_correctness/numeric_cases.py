"""Additional independently specified synthetic TRAIN requirements."""
from suite.progress_correctness.more_cases import add

F = 'train-billing'
add(F, 'discount', 'Create discount.py with price(amount, percent). Both are nonnegative integer cents and whole percent respectively, with percent from 0 through 100. Return the discounted integer cent amount rounded down.',
'''def price(amount, percent):
    return amount * (100 - percent) // 100
''',
'''def price(amount, percent):
    discount = amount * percent // 100
    return amount - discount
''',
'''from discount import price
assert price(1000, 20) == 800
assert price(300, 0) == 300
''',
'''from discount import price
assert price(101, 50) == 50
''','rounding')
add(F,'tax', 'Create tax.py with tax(cents, rate): both arguments are nonnegative integers; rate is a whole percent and may exceed 100. Return tax in cents rounded up to the next cent whenever there is a remainder.',
'''def tax(cents, rate):
    return -(-(cents * rate) // 100)
''',
'''def tax(cents, rate):
    rate = min(rate, 100)
    return -(-(cents * rate) // 100)
''',
'''from tax import tax
assert tax(1000, 10) == 100
assert tax(101, 10) == 11
assert tax(0, 10) == 0
''',
'''from tax import tax
assert tax(101, 150) == 152
''','rounding')
add(F,'tiers', 'Create tiers.py with shipping(weight): return 5 for nonnegative weights up to and including 2, 9 for weights greater than 2 up to and including 5, and 15 for weights over 5.',
'''def shipping(weight):
    if weight <= 2: return 5
    if weight <= 5: return 9
    return 15
''',
'''def shipping(weight):
    if weight < 2: return 5
    if weight < 5: return 9
    return 15
''',
'''from tiers import shipping
assert shipping(1) == 5
assert shipping(3) == 9
assert shipping(6) == 15
''',
'''from tiers import shipping
assert shipping(2) == 5
assert shipping(5) == 9
''','boundary')
add(F,'change', 'Create change.py with coins(cents), for nonnegative integer cents. Return the minimum count of coins of denominations 25, 10, 5 and 1 needed to make the amount.',
'''def coins(cents):
    total = 0
    for value in (25, 10, 5, 1):
        n, cents = divmod(cents, value)
        total += n
    return total
''',
'''def coins(cents):
    total = 0
    for value in (25, 10, 5):
        n, cents = divmod(cents, value)
        total += n
    return total
''',
'''from change import coins
assert coins(40) == 3
assert coins(0) == 0
''',
'''from change import coins
assert coins(41) == 4
''','omitted-denomination')
add(F,'invoice', 'Create invoice.py with total(items), where each item is (integer cents, signed integer quantity). Negative quantities represent returns and must be subtracted. Return the sum of price times quantity; an empty invoice totals zero.',
'''def total(items):
    return sum(price * quantity for price, quantity in items)
''',
'''def total(items):
    result = 0
    for price, quantity in items:
        if quantity > 0:
            result += price * quantity
    return result
''',
'''from invoice import total
assert total([]) == 0
assert total([(2, 2)]) == 4
assert total([(100, 3), (20, 2)]) == 340
''',
'''from invoice import total
assert total([(100, 3), (20, -2)]) == 260
''','signed-quantity')

F = 'train-geometry'
add(F,'clamp', 'Create clamp.py with clamp(value, lower, upper), where lower <= upper. Return the nearest bound when value is outside the closed range, otherwise return value.',
'''def clamp(value, lower, upper):
    return min(upper, max(lower, value))
''',
'''def clamp(value, lower, upper):
    if value < lower:
        return lower
    return value
''',
'''from clamp import clamp
assert clamp(-3, 0, 10) == 0
assert clamp(5, 0, 10) == 5
''',
'''from clamp import clamp
assert clamp(12, 0, 10) == 10
''','missing-branch')
add(F,'rectangle', 'Create rectangle.py with contains(rect, point). rect is (left, top, right, bottom) and point is (x, y); edges are included. Return whether the point lies inside or on the rectangle.',
'''def contains(rect, point):
    l, t, r, b = rect
    x, y = point
    return l <= x <= r and t <= y <= b
''',
'''def contains(rect, point):
    l, t, r, b = rect
    x, y = point
    return l <= x < r and t <= y < b
''',
'''from rectangle import contains
assert contains((0, 0, 4, 3), (1, 1)) is True
assert contains((0, 0, 4, 3), (9, 1)) is False
''',
'''from rectangle import contains
assert contains((0, 0, 4, 3), (4, 3)) is True
''','boundary')
add(F,'distance', 'Create distance.py with manhattan(a, b), returning the sum of absolute horizontal and vertical differences between two (x, y) points.',
'''def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
''',
'''def manhattan(a, b):
    return abs(a[0] - b[0]) + (a[1] - b[1])
''',
'''from distance import manhattan
assert manhattan((3, 4), (1, 1)) == 5
assert manhattan((0, 0), (0, 0)) == 0
''',
'''from distance import manhattan
assert manhattan((0, 0), (2, 3)) == 5
''','sign')
add(F,'intersect', 'Create intersect.py with intersection(a, b), where each is a set of integer coordinates. Return a new set containing elements present in both inputs, without mutating either input.',
'''def intersection(a, b):
    return a & b
''',
'''def intersection(a, b):
    a.intersection_update(b)
    return a
''',
'''from intersect import intersection
assert intersection({1, 2}, {2, 3}) == {2}
assert intersection(set(), {2}) == set()
''',
'''from intersect import intersection
a, b = {1, 2}, {2, 3}
r = intersection(a, b)
assert a == {1, 2} and b == {2, 3}
assert r is not a and r is not b
''','mutation')
add(F,'rotate', 'Create rotate.py with rotate90(point), returning the integer point obtained by rotating (x, y) 90 degrees counterclockwise around the origin, and flip_x(point), returning the reflection across the y-axis.',
'''def rotate90(point):
    x, y = point
    return -y, x

def flip_x(point):
    x, y = point
    return -x, y
''',
'''def rotate90(point):
    x, y = point
    return y, x

def flip_x(point):
    x, y = point
    return -x, y
''',
'''from rotate import rotate90, flip_x
assert rotate90((0, 0)) == (0, 0)
assert rotate90((2, 0)) == (0, 2)
assert flip_x((3, -2)) == (-3, -2)
''',
'''from rotate import rotate90
assert rotate90((0, 3)) == (-3, 0)
''','sign')
