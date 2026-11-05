"""Hand-authored TRAIN families; requirements and oracles are independent of implementations."""

CASES = []


def add(family, name, requirement, complete, partial, ordinary, omission, defect, language="Python"):
    ext = {"Python": "py", "JavaScript": "js", "Ruby": "rb"}[language]
    path = f"{name}.{ext}"
    unrelated = {
        "Python": {"formatting.py": '''def format_title(title):
    words = title.strip().split()
    return " ".join(word.capitalize() for word in words)


def format_list(items):
    if not items:
        return "(none)"
    return "\\n".join(f"- {item}" for item in items)
'''},
        "JavaScript": {"formatting.js": '''exports.formatTitle = text => text.trim().split(/\\s+/)
  .map(word => word[0].toUpperCase() + word.slice(1)).join(' ');
exports.formatList = items => items.length
  ? items.map(item => `- ${item}`).join('\\n')
  : '(none)';
'''},
        "Ruby": {"formatting.rb": '''def format_title(text)
  text.strip.split.map(&:capitalize).join(' ')
end

def format_list(items)
  return '(none)' if items.empty?
  items.map { |item| "- #{item}" }.join("\\n")
end
'''},
    }[language]
    # Independent project features, not task implementations. Every variant is
    # authored in TRAIN; distribute unrelated edits across all three classes.
    other_python = {
        'train-scheduling': ('contacts.py', '''def email_domain(address):
    return address.rsplit('@', 1)[-1].lower()

def group_by_domain(addresses):
    groups = {}
    for address in addresses:
        groups.setdefault(email_domain(address), []).append(address)
    return groups
'''),
        'train-text-index': ('calendar_view.py', '''def month_heading(year, month):
    from calendar import month_name
    return f"{month_name[month]} {year}"

def year_headings(year):
    return [month_heading(year, month) for month in range(1, 13)]
'''),
        'train-billing': ('catalog.py', '''def active_items(items):
    return [item for item in items if item.get('active', True)]

def names(items):
    return [item['name'] for item in active_items(items)]
'''),
        'train-geometry': ('palette.py', '''def hex_color(red, green, blue):
    return f"#{red:02x}{green:02x}{blue:02x}"

def grayscale(level):
    return hex_color(level, level, level)
'''),
        'train-file-records': ('labels.py', '''def display_name(first, last):
    return ' '.join(part.strip() for part in (first, last) if part.strip())

def initials(first, last):
    return ''.join(part.strip()[:1].upper() for part in (first, last))
'''),
        'train-collections': ('metrics.py', '''def mean(values):
    return sum(values) / len(values) if values else None

def spread(values):
    return max(values) - min(values) if values else None
'''),
        'train-cli-integration': ('paths.py', '''from pathlib import Path

def filenames(directory):
    return sorted(path.name for path in Path(directory).iterdir() if path.is_file())

def suffixes(directory):
    return sorted({Path(name).suffix for name in filenames(directory)})
'''),
    }
    if family in other_python:
        other_path, other_text = other_python[family]
        unrelated = {other_path: other_text}
    index = len(CASES)
    CASES.append({"family": family, "group": f"{family}/{name}", "language": language, "defect": defect,
                  "requirement": requirement, "path": path, "seed": "", "complete": complete,
                  "partial": partial, "unrelated": unrelated if index % 4 else {},
                  "done_distractors": unrelated if index % 2 == 0 else {},
                  "partial_distractors": unrelated if index % 2 else {},
                  "checks": {"ordinary": ordinary, "omission": omission},
                  "rationale": "Requirement-derived boundary and normal-case assertions are retained in verifier_programs."})

# Family assignments precede these authored variants. Distinct modules express distinct requirements.
F = "train-scheduling"
add(F,"overlap", "Create overlap.py with overlap(a, b), where each argument is a (start, end) half-open interval. Return True iff the intervals share a point; touching endpoints are not overlap, and an empty interval never overlaps.",
'''def overlap(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])
''',
'''def overlap(a, b):
    if a[0] > a[1] or b[0] > b[1]:
        return False
    return max(a[0], b[0]) <= min(a[1], b[1])
''',
'''from overlap import overlap
assert overlap((1, 5), (3, 7)) is True
assert overlap((1, 2), (4, 8)) is False
''',
'''from overlap import overlap
assert overlap((1, 2), (2, 4)) is False
assert overlap((2, 2), (1, 3)) is False
''',"boundary")
add(F,"duration", "Create duration.py with minutes(start, end): start and end are nonnegative minutes after midnight, with end at or after start. Return whole elapsed hours and remaining minutes as a two-item tuple.",
'''def minutes(start, end):
    return divmod(end - start, 60)
''',
'''def minutes(start, end):
    difference = end - start
    hours = difference // 60
    remainder = difference % 100
    return hours, remainder
''',
'''from duration import minutes
assert minutes(10, 40) == (0, 30)
assert minutes(10, 10) == (0, 0)
''',
'''from duration import minutes
assert minutes(30, 155) == (2, 5)
''',"wrong-unit")
add(F,"slots", "Create slots.py with starts(start, end, step), returning start times spaced by positive step from start while strictly less than end, as a list. When start is at or beyond end return an empty list.",
'''def starts(start, end, step):
    return list(range(start, end, step))
''',
'''def starts(start, end, step):
    values = []
    while start <= end:
        values.append(start)
        start += step
    return values
''',
'''from slots import starts
assert starts(0, 5, 2) == [0, 2, 4]
assert starts(7, 6, 1) == []
''',
'''from slots import starts
assert starts(0, 6, 2) == [0, 2, 4]
assert starts(2, 2, 1) == []
''',"off-by-one")
add(F,"timezone", "Create timezone.py with local_hour(utc_hour, offset): both arguments are integers, utc_hour is 0 through 23, and offset is any signed number of whole hours. Return the local hour wrapped into 0 through 23.",
'''def local_hour(utc_hour, offset):
    return (utc_hour + offset) % 24
''',
'''def local_hour(utc_hour, offset):
    hour = utc_hour + offset
    if hour >= 24:
        hour -= 24
    if hour < 0:
        hour += 24
    return hour
''',
'''from timezone import local_hour
assert local_hour(23, 2) == 1
assert local_hour(1, -3) == 22
''',
'''from timezone import local_hour
assert local_hour(1, 49) == 2
assert local_hour(1, -50) == 23
''',"large-offset")
add(F,"weekdays", "Create weekdays.py with next_day(day), accepting English lowercase weekday names and returning the following lowercase weekday. Sunday wraps to Monday; raise ValueError for an unknown name.",
'''def next_day(day):
    days = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    return days[(days.index(day) + 1) % len(days)]
''',
'''def next_day(day):
    days = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    if day not in days:
        raise ValueError(day)
    i = days.index(day)
    return days[i + 1]
''',
'''from weekdays import next_day
assert next_day('monday') == 'tuesday'
try: next_day('other')
except ValueError: pass
else: raise AssertionError('invalid day')
''',
'''from weekdays import next_day
assert next_day('sunday') == 'monday'
''',"wraparound")

F = "train-text-index"
add(F,"prefix", "Create prefix.py with longest_prefix(words), returning the longest case-sensitive prefix shared by all strings; return the empty string for an empty list or if no prefix is shared.",
'''def longest_prefix(words):
    if not words:
        return ''
    result = words[0]
    for word in words[1:]:
        while not word.startswith(result):
            result = result[:-1]
    return result
''',
'''def longest_prefix(words):
    if not words:
        return ''
    result = words[0]
    for word in words[1:]:
        while result and not word.lower().startswith(result.lower()):
            result = result[:-1]
    return result
''',
'''from prefix import longest_prefix
assert longest_prefix(['flower','flow','flight']) == 'fl'
assert longest_prefix([]) == ''
''',
'''from prefix import longest_prefix
assert longest_prefix(['Sun', 'sun']) == ''
''',"case-sensitivity")
add(F,"excerpt", "Create excerpt.py with excerpt(text, limit): return text unchanged when its length is at most the nonnegative limit; otherwise return its first limit characters followed by a single Unicode ellipsis character.",
'''def excerpt(text, limit):
    return text if len(text) <= limit else text[:limit] + '…'
''',
'''def excerpt(text, limit):
    if len(text) < limit:
        return text
    return text[:limit] + '…'
''',
'''from excerpt import excerpt
assert excerpt('abcd', 2) == 'ab…'
assert excerpt('x', 2) == 'x'
''',
'''from excerpt import excerpt
assert excerpt('abcd', 4) == 'abcd'
assert excerpt('', 0) == ''
''',"boundary")
add(F,"tokens", "Create tokens.py with counts(text). Split on whitespace, lowercase each token, and return a dictionary mapping each token to its count. Empty or whitespace-only input returns an empty dictionary.",
'''def counts(text):
    result = {}
    for word in text.lower().split():
        result[word] = result.get(word, 0) + 1
    return result
''',
'''def counts(text):
    result = {}
    for word in text.split():
        result[word] = result.get(word, 0) + 1
    return result
''',
'''from tokens import counts
assert counts('a b a') == {'a': 2, 'b': 1}
assert counts('  ') == {}
''',
'''from tokens import counts
assert counts('Red red RED') == {'red': 3}
''',"normalization")
add(F,"slug", "Create slug.py with slug(text): trim surrounding whitespace, lowercase, and join nonempty whitespace-separated words with hyphens. Preserve punctuation inside words. Empty input produces the empty string.",
'''def slug(text):
    return '-'.join(text.lower().split())
''',
'''def slug(text):
    words = text.strip().lower().split(' ')
    return '-'.join(w for w in words if w)
''',
'''from slug import slug
assert slug('  Hello WORLD  ') == 'hello-world'
assert slug(' ') == ''
''',
'''from slug import slug
assert slug('one\\ttwo\\nthree') == 'one-two-three'
''',"whitespace")
add(F,"lines", "Create lines.py with numbered(text): use Python str.splitlines() to identify lines, omit zero-length lines, and prefix every remaining line with its original one-based line number and ': '. Preserve line contents exactly, including whitespace-only lines; do not renumber after omissions. Return a list of strings.",
'''def numbered(text):
    return [f'{i}: {line}' for i, line in enumerate(text.splitlines(), 1) if line]
''',
'''def numbered(text):
    kept = [line for line in text.splitlines() if line]
    return [f'{i}: {line}' for i, line in enumerate(kept, 1)]
''',
'''from lines import numbered
assert numbered('red\\nblue') == ['1: red', '2: blue']
assert numbered(' \\nnext') == ['1:  ', '2: next']
assert numbered('x\\u2028y') == ['1: x', '2: y']
assert numbered('') == []
''',
'''from lines import numbered
assert numbered('red\\n\\nblue') == ['1: red', '3: blue']
''',"source-position")
