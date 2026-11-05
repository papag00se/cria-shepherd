"""TRAIN cross-file integration and requested-test requirements."""
from suite.progress_correctness.more_cases import add, CASES

F = 'train-cli-integration'

def integration(name, requirement, library, good_cli, bad_cli, ordinary, omission):
    add(F, name, requirement, library, library, ordinary, omission, 'integration')
    case = CASES[-1]
    case['complete_files'] = {name + '.py': library, 'app.py': good_cli}
    case['partial_files'] = {name + '.py': library, 'app.py': bad_cli}

integration('greet', 'Add greet.py with greeting(name), returning "Hello, " followed by name. Add app.py: when run as a script, print greeting for its first command-line argument.',
'''def greeting(name):
    return 'Hello, ' + name
''',
'''import sys
from greet import greeting
if __name__ == '__main__':
    print(greeting(sys.argv[1]))
''',
'''import sys
from greet import greeting
if __name__ == '__main__':
    print(sys.argv[1])
''',
'''from greet import greeting
assert greeting('Mira') == 'Hello, Mira'
''',
'''import subprocess, sys
p = subprocess.run([sys.executable, 'app.py', 'Mira'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0 and p.stdout == 'Hello, Mira\\n'
''')
integration('convert', 'Add convert.py with celsius_to_f(c), returning c * 9 / 5 + 32. Add app.py: when run with a numeric Celsius argument, print the Fahrenheit value.',
'''def celsius_to_f(c):
    return c * 9 / 5 + 32
''',
'''import sys
from convert import celsius_to_f
if __name__ == '__main__':
    print(celsius_to_f(float(sys.argv[1])))
''',
'''import sys
from convert import celsius_to_f
if __name__ == '__main__':
    print(float(sys.argv[1]))
''',
'''from convert import celsius_to_f
assert celsius_to_f(0) == 32
assert celsius_to_f(100) == 212
''',
'''import subprocess, sys
p = subprocess.run([sys.executable, 'app.py', '0'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0 and float(p.stdout) == 32
''')
integration('sumcost', 'Add sumcost.py with total(prices) returning the sum. Add app.py: when invoked with integer command-line arguments, print their total; with no arguments print 0.',
'''def total(prices):
    return sum(prices)
''',
'''import sys
from sumcost import total
if __name__ == '__main__':
    print(total([int(x) for x in sys.argv[1:]]))
''',
'''import sys
from sumcost import total
if __name__ == '__main__':
    print(total([int(x) for x in sys.argv[1:2]]))
''',
'''from sumcost import total
assert total([2, 3]) == 5
assert total([]) == 0
''',
'''import subprocess, sys
p = subprocess.run([sys.executable, 'app.py', '2', '3'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0 and p.stdout == '5\\n'
''')
integration('quote', 'Add quote.py with quoted(s), wrapping s in square brackets. Add app.py: when invoked with a single argument, print the quoted argument followed by a newline.',
'''def quoted(s):
    return '[' + s + ']'
''',
'''import sys
from quote import quoted
if __name__ == '__main__':
    print(quoted(sys.argv[1]))
''',
'''import sys
from quote import quoted
if __name__ == '__main__':
    print(quoted(sys.argv[1]), end='')
''',
'''from quote import quoted
assert quoted('x') == '[x]'
assert quoted('') == '[]'
''',
'''import subprocess, sys
p = subprocess.run([sys.executable, 'app.py', 'x'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0 and p.stdout == '[x]\\n'
''')

add(F,'rate', 'Create rate.py with reciprocal(x), returning 1 / x for nonzero x and raising ValueError for zero. Also create test_rate.py with unittest tests that exercise both a nonzero input and the zero exception.',
'''def reciprocal(x):
    if x == 0:
        raise ValueError('zero')
    return 1 / x
''',
'''def reciprocal(x):
    if x == 0:
        raise ValueError('zero')
    return 1 / x
''',
'''from rate import reciprocal
assert reciprocal(4) == 0.25
try: reciprocal(0)
except ValueError: pass
else: raise AssertionError('zero')
''',
'''import subprocess, sys
from pathlib import Path
assert Path('test_rate.py').is_file()
p = subprocess.run([sys.executable, '-m', 'unittest', 'test_rate'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0 and 'Ran 2 tests' in p.stderr
Path('rate.py').write_text('def reciprocal(x):\\n    return 1 / x if x else 0\\n')
p = subprocess.run([sys.executable, '-m', 'unittest', 'test_rate'], capture_output=True, text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode != 0, 'tests must detect missing ValueError'
''','requested-tests')
case = CASES[-1]
case['complete_files'] = {'rate.py': case['complete'], 'test_rate.py': '''import unittest
from rate import reciprocal

class RateTests(unittest.TestCase):
    def test_nonzero(self):
        self.assertEqual(reciprocal(4), 0.25)

    def test_zero(self):
        with self.assertRaises(ValueError):
            reciprocal(0)
'''}
case['partial_files'] = {'rate.py': case['partial'], 'test_rate.py': '''import unittest
from rate import reciprocal

class RateTests(unittest.TestCase):
    def test_nonzero(self):
        self.assertEqual(reciprocal(4), 0.25)
'''}
