"""Hand-authored JavaScript and Ruby TRAIN requirements."""
from suite.progress_correctness.more_cases import add

F = 'train-web-helpers'
add(F,'query', 'Create query.js exporting parameter(params, name), returning the named own property as a string, or null if absent. A present empty string must remain empty.',
'''exports.parameter = (params, name) => Object.hasOwn(params, name) ? String(params[name]) : null;
''',
'''exports.parameter = (params, name) => params[name] ? String(params[name]) : null;
''',
'''const assert = require('node:assert/strict');
const {parameter} = require('./query');
assert.equal(parameter({q: 'word'}, 'q'), 'word');
assert.equal(parameter({}, 'q'), null);
''',
'''const assert = require('node:assert/strict');
const {parameter} = require('./query');
assert.equal(parameter({q: ''}, 'q'), '');
assert.equal(parameter({n: 0}, 'n'), '0');
''','falsy-value','JavaScript')
add(F,'headers', 'Create headers.js exporting getHeader(headers, name). Find a property whose key equals name ignoring ASCII case, and return its value; return null when absent. There is at most one matching key.',
'''exports.getHeader = function(headers, name) {
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === name.toLowerCase()) return value;
  }
  return null;
};
''',
'''exports.getHeader = function(headers, name) {
  return Object.hasOwn(headers, name) ? headers[name] : null;
};
''',
'''const assert = require('node:assert/strict');
const {getHeader} = require('./headers');
assert.equal(getHeader({'accept':'text'}, 'accept'), 'text');
assert.equal(getHeader({}, 'accept'), null);
''',
'''const assert = require('node:assert/strict');
const {getHeader} = require('./headers');
assert.equal(getHeader({'Content-Type':'json'}, 'content-type'), 'json');
''','case-sensitivity','JavaScript')
add(F,'limit', 'Create limit.js exporting take(items, n), returning a new array containing at most the first n elements, with nonnegative integer n. Never mutate the input array.',
'''exports.take = (items, n) => items.slice(0, n);
''',
'''exports.take = function(items, n) {
  return items.splice(0, n);
};
''',
'''const assert = require('node:assert/strict');
const {take} = require('./limit');
assert.deepEqual(take([1,2,3], 2), [1,2]);
assert.deepEqual(take([], 3), []);
''',
'''const assert = require('node:assert/strict');
const {take} = require('./limit');
const a = [1,2,3]; const result = take(a, 2);
assert.deepEqual(a, [1,2,3]);
assert.notEqual(result, a);
''','mutation','JavaScript')
add(F,'status', 'Create status.js exporting isSuccess(code), which is true for integer HTTP status codes from 200 through 299 inclusive and false otherwise.',
'''exports.isSuccess = code => Number.isInteger(code) && code >= 200 && code < 300;
''',
'''exports.isSuccess = code => Number.isInteger(code) && code > 200 && code < 300;
''',
'''const assert = require('node:assert/strict');
const {isSuccess} = require('./status');
assert.equal(isSuccess(204), true);
assert.equal(isSuccess(404), false);
assert.equal(isSuccess(250.5), false);
assert.equal(isSuccess('250'), false);
assert.equal(isSuccess(null), false);
''',
'''const assert = require('node:assert/strict');
const {isSuccess} = require('./status');
assert.equal(isSuccess(200), true);
assert.equal(isSuccess(299), true);
''','boundary','JavaScript')
add(F,'escape_html', 'Create escape_html.js exporting escapeHtml(text). Replace each ampersand, less-than sign, and greater-than sign with &amp;, &lt;, and &gt; respectively; leave all other characters unchanged.',
'''exports.escapeHtml = text => text.replace(/[&<>]/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;'})[c]);
''',
'''exports.escapeHtml = text => text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
''',
'''const assert = require('node:assert/strict');
const {escapeHtml} = require('./escape_html');
assert.equal(escapeHtml('<x>'), '&lt;x&gt;');
assert.equal(escapeHtml('plain'), 'plain');
''',
'''const assert = require('node:assert/strict');
const {escapeHtml} = require('./escape_html');
assert.equal(escapeHtml('a&b'), 'a&amp;b');
''','omitted-character','JavaScript')

F = 'train-library-ruby'
add(F,'median', 'Create median.rb defining median(values) for a nonempty array of numbers. Return the middle value after sorting, or the average of the two middle values when the length is even; do not mutate the input.',
'''def median(values)
  ordered = values.sort
  mid = ordered.length / 2
  ordered.length.odd? ? ordered[mid] : (ordered[mid - 1] + ordered[mid]) / 2.0
end
''',
'''def median(values)
  ordered = values.sort
  ordered[ordered.length / 2]
end
''',
'''require_relative './median'
raise unless median([3, 1, 2]) == 2
raise unless median([7]) == 7
''',
'''require_relative './median'
a = [8, 2, 4, 6]
raise unless median(a) == 5.0
raise unless a == [8, 2, 4, 6]
''','even-length','Ruby')
add(F,'frequency', 'Create frequency.rb defining frequency(words), returning a hash of each string to the number of occurrences, treating case distinctly. Empty input returns an empty hash.',
'''def frequency(words)
  words.each_with_object(Hash.new(0)) { |word, counts| counts[word] += 1 }
end
''',
'''def frequency(words)
  words.each_with_object(Hash.new(0)) { |word, counts| counts[word.downcase] += 1 }
end
''',
'''require_relative './frequency'
raise unless frequency(['a', 'b', 'a']) == {'a' => 2, 'b' => 1}
raise unless frequency([]) == {}
''',
'''require_relative './frequency'
raise unless frequency(['A', 'a']) == {'A' => 1, 'a' => 1}
''','case-sensitivity','Ruby')
add(F,'suffix', 'Create suffix.rb defining suffix(path), returning the text after the last dot in the final slash-separated path component, or an empty string when there is no dot. The returned suffix excludes the dot.',
'''def suffix(path)
  name = path.split('/', -1).last || ''
  index = name.rindex('.')
  index ? name[(index + 1)..] : ''
end
''',
'''def suffix(path)
  index = path.rindex('.')
  index ? path[(index + 1)..] : ''
end
''',
'''require_relative './suffix'
raise unless suffix('a/file.tar.gz') == 'gz'
raise unless suffix('file') == ''
''',
'''require_relative './suffix'
raise unless suffix('dir.ext/file') == ''
raise unless suffix('dir.ext/') == ''
''','path-component','Ruby')
add(F,'balances', 'Create balances.rb defining balances(changes), returning an array of cumulative sums after each numeric change in order. Empty input returns an empty array.',
'''def balances(changes)
  value = 0
  changes.map { |change| value += change }
end
''',
'''def balances(changes)
  value = 0
  changes.map do |change|
    if change >= 0
      value += change
    else
      value = change
    end
  end
end
''',
'''require_relative './balances'
raise unless balances([2]) == [2]
raise unless balances([3, 2, 4]) == [3, 5, 9]
raise unless balances([]) == []
''',
'''require_relative './balances'
raise unless balances([3, -1, 4]) == [3, 2, 6]
''','state','Ruby')
add(F,'title', 'Create title.rb defining title(words), joining an array of strings with one space and capitalizing only the first character of the entire result. Empty input returns an empty string.',
'''def title(words)
  text = words.join(' ')
  text.empty? ? text : text[0].upcase + text[1..]
end
''',
'''def title(words)
  words.map(&:capitalize).join(' ')
end
''',
'''require_relative './title'
raise unless title(['hello']) == 'Hello'
raise unless title([]) == ''
''',
'''require_relative './title'
raise unless title(['hello', 'WORLD']) == 'Hello WORLD'
''','format','Ruby')
