"""Storage and collection TRAIN requirements, authored before their implementations."""
from suite.progress_correctness.more_cases import add

F = 'train-file-records'
add(F,'append_event', 'Create append_event.py with append_event(path, event): append the event and a newline as UTF-8 text to the file at path, creating it if absent and preserving existing content.',
'''def append_event(path, event):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(event + '\\n')
''',
'''def append_event(path, event):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(event + '\\n')
''',
'''from append_event import append_event
from pathlib import Path
p = Path('events.dat')
append_event(p, 'created')
assert p.read_text(encoding='utf-8') == 'created\\n'
''',
'''from append_event import append_event
from pathlib import Path
p = Path('events.dat')
p.write_text('first\\n', encoding='utf-8')
append_event(p, 'second')
assert p.read_text(encoding='utf-8') == 'first\\nsecond\\n'
''','persistence')
add(F,'preferences', 'Create preferences.py with set_theme(path, theme). The UTF-8 JSON file contains an object; replace or add its theme property and write the object back, preserving every other property. If the file does not exist, create it with only the theme property.',
'''import json
from pathlib import Path

def set_theme(path, theme):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    data['theme'] = theme
    path.write_text(json.dumps(data), encoding='utf-8')
''',
'''import json
from pathlib import Path

def set_theme(path, theme):
    path = Path(path)
    path.write_text(json.dumps({'theme': theme}), encoding='utf-8')
''',
'''from preferences import set_theme
from pathlib import Path
import json
p = Path('prefs.json')
set_theme(p, 'dark')
assert json.loads(p.read_text()) == {'theme': 'dark'}
''',
'''from preferences import set_theme
from pathlib import Path
import json
p = Path('prefs.json')
p.write_text('{"font": "serif", "theme": "light"}')
set_theme(p, 'dark')
assert json.loads(p.read_text()) == {'font': 'serif', 'theme': 'dark'}
''','persistence')
add(F,'read_config', 'Create read_config.py with read_port(path): read a UTF-8 file containing an integer in Python int() base-10 syntax, allowing surrounding whitespace, and return the integer. Raise ValueError if it is outside 1 through 65535 or not an integer. Propagate file access errors.',
'''def read_port(path):
    with open(path, encoding='utf-8') as f:
        port = int(f.read().strip())
    if not 1 <= port <= 65535:
        raise ValueError('port out of range')
    return port
''',
'''def read_port(path):
    with open(path, encoding='utf-8') as f:
        port = int(f.read().strip())
    if not 0 <= port <= 65535:
        raise ValueError('port out of range')
    return port
''',
'''from read_config import read_port
from pathlib import Path
p = Path('port.txt'); p.write_text(' 8080 ')
assert read_port(p) == 8080
p.write_text('1_0'); assert read_port(p) == 10
p.write_text('+80'); assert read_port(p) == 80
p.write_text('bad')
try: read_port(p)
except ValueError: pass
else: raise AssertionError('invalid')
try: read_port('absent-port-file')
except FileNotFoundError: pass
else: raise AssertionError('missing file')
''',
'''from read_config import read_port
from pathlib import Path
p = Path('port.txt'); p.write_text('0')
try: read_port(p)
except ValueError: pass
else: raise AssertionError('zero accepted')
''','validation')
add(F,'remove_entry', 'Create remove_entry.py with remove(path, target): read a UTF-8 file of LF-terminated names containing no carriage returns and rewrite it omitting every line exactly equal to target; preserve the order and text of all other lines.',
'''def remove(path, target):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(line for line in lines if line.rstrip('\\n') != target)
''',
'''def remove(path, target):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    if target + '\\n' in lines:
        lines.remove(target + '\\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
''',
'''from remove_entry import remove
from pathlib import Path
p = Path('names'); p.write_text('a\\nb\\n')
remove(p, 'a')
assert p.read_text() == 'b\\n'
''',
'''from remove_entry import remove
from pathlib import Path
p = Path('names'); p.write_text('a\\nb\\na\\n')
remove(p, 'a')
assert p.read_text() == 'b\\n'
''','persistence')
add(F,'unique_file', 'Create unique_file.py with write_unique(path, names): write each distinct string from names, which contain no line breaks, on its own UTF-8 line, preserving order of first occurrence. Overwrite any previous file, and write an empty file for an empty list.',
'''def write_unique(path, names):
    with open(path, 'w', encoding='utf-8') as f:
        for name in dict.fromkeys(names):
            f.write(name + '\\n')
''',
'''def write_unique(path, names):
    with open(path, 'a', encoding='utf-8') as f:
        for name in dict.fromkeys(names):
            f.write(name + '\\n')
''',
'''from unique_file import write_unique
from pathlib import Path
p = Path('names'); write_unique(p, ['a', 'b', 'a'])
assert p.read_text() == 'a\\nb\\n'
''',
'''from unique_file import write_unique
from pathlib import Path
p = Path('names'); p.write_text('old\\n')
write_unique(p, [])
assert p.read_text() == ''
''','persistence')

F = 'train-collections'
add(F,'chunks', 'Create chunks.py with chunks(values, size), with positive size, returning consecutive lists of at most size elements, including a final shorter chunk. Empty input returns an empty list.',
'''def chunks(values, size):
    return [values[i:i+size] for i in range(0, len(values), size)]
''',
'''def chunks(values, size):
    result = []
    for i in range(0, len(values), size):
        chunk = values[i:i+size]
        if len(chunk) == size:
            result.append(chunk)
    return result
''',
'''from chunks import chunks
assert chunks([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
assert chunks([], 3) == []
''',
'''from chunks import chunks
assert chunks([1, 2, 3], 2) == [[1, 2], [3]]
''','omitted-tail')
add(F,'flatten', 'Create flatten.py with flatten(rows), returning a new list containing each element of each input list in row order, including duplicates. Empty rows contribute nothing.',
'''def flatten(rows):
    return [item for row in rows for item in row]
''',
'''def flatten(rows):
    result = []
    for row in rows:
        for item in row:
            if item not in result:
                result.append(item)
    return result
''',
'''from flatten import flatten
assert flatten([[1, 2], [], [3]]) == [1, 2, 3]
assert flatten([]) == []
''',
'''from flatten import flatten
assert flatten([[1], [1, 2]]) == [1, 1, 2]
''','duplicate-preservation')
add(F,'index_of', 'Create index_of.py with first(values, target): return the zero-based index of the first equal element, or -1 if no element equals target.',
'''def first(values, target):
    for i, value in enumerate(values):
        if value == target:
            return i
    return -1
''',
'''def first(values, target):
    answer = -1
    for i, value in enumerate(values):
        if value == target:
            answer = i
    return answer
''',
'''from index_of import first
assert first([1, 2, 3], 2) == 1
assert first([], 2) == -1
''',
'''from index_of import first
assert first([2, 1, 2], 2) == 0
''','first-vs-last')
add(F,'histogram', 'Create histogram.py with bins(values), returning a dictionary mapping each integer to its occurrence count. The result for an empty list is an empty dictionary.',
'''def bins(values):
    from collections import Counter
    return dict(Counter(values))
''',
'''def bins(values):
    result = {}
    for value in values:
        if value >= 0:
            result[value] = result.get(value, 0) + 1
        else:
            result[value] = 1
    return result
''',
'''from histogram import bins
assert bins([1, 2, 2]) == {1: 1, 2: 2}
assert bins([]) == {}
''',
'''from histogram import bins
assert bins([-2, -2, 1]) == {-2: 2, 1: 1}
''','counting')
add(F,'window', 'Create window.py with pairs(values), returning a list of overlapping consecutive two-element tuples, in order. Fewer than two elements gives an empty list.',
'''def pairs(values):
    return list(zip(values, values[1:]))
''',
'''def pairs(values):
    return [(values[i], values[i+1]) for i in range(0, len(values)-1, 2)]
''',
'''from window import pairs
assert pairs([1, 2]) == [(1, 2)]
assert pairs([1]) == []
''',
'''from window import pairs
assert pairs([1, 2, 3]) == [(1, 2), (2, 3)]
''','overlap')
