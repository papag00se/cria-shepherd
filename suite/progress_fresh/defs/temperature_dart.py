from suite.progress_fresh.dsl import ed

SEED = {
"lib/temp.dart": '''double cToF(double c) => c * 9 / 5 + 32;

double fToC(double f) => (f - 32) * 5 / 9;

String describe(double c) {
  if (c < 10) return 'cold';
  if (c < 25) return 'mild';
  return 'hot';
}
''',
"bin/main.dart": '''import 'package:temp/temp.dart';

void main(List<String> args) {
  final c = double.parse(args.first);
  print('${cToF(c).toStringAsFixed(1)} F, ${describe(c)}');
}
''',
"test/temp_test.dart": '''import 'package:temp/temp.dart';
import 'package:test/test.dart';

void main() {
  test('cToF', () => expect(cToF(100), 212));
  test('fToC', () => expect(fToC(32), 0));
}
''',
}
L = SEED["lib/temp.dart"]
M = SEED["bin/main.dart"]
T = SEED["test/temp_test.dart"]
KEL_L = "\ndouble cToK(double c) => c + 273.15;\n\ndouble kToC(double k) => k - 273.15;\n"
TASK = dict(extension=True, name="temperature-dart", language="Dart", seed=SEED,
unrelated={"bin/main.dart": "// usage: dart run bin/main.dart <celsius>\n" + M},
reqs=[
dict(id="kelvin", text="Add Kelvin support: cToK and kToC in lib/temp.dart, with kToC throwing ArgumentError for values below absolute zero, and tests for both functions including the error.",
 partial={"lib/temp.dart": L + KEL_L, "test/temp_test.dart": ed(T, ("}\n", "  test('cToK', () => expect(cToK(0), 273.15));\n  test('kToC', () => expect(kToC(273.15), 0));\n}\n"))},
 done={"lib/temp.dart": L + "\ndouble cToK(double c) => c + 273.15;\n\ndouble kToC(double k) {\n  if (k < 0) throw ArgumentError('below absolute zero: $k');\n  return k - 273.15;\n}\n",
       "test/temp_test.dart": ed(T, ("}\n", "  test('cToK', () => expect(cToK(0), 273.15));\n  test('kToC', () => expect(kToC(273.15), 0));\n  test('kToC rejects below absolute zero',\n      () => expect(() => kToC(-1), throwsArgumentError));\n}\n"))}),
dict(id="describe-edges", text="describe() should treat exactly 10 as 'mild' and exactly 25 as 'hot' (boundaries belong to the warmer band), return 'freezing' below 0, and throw ArgumentError for NaN.", ns=True,
 partial={"lib/temp.dart": ed(L, ("  if (c < 10) return 'cold';", "  if (c < 0) return 'freezing';\n  if (c < 10) return 'cold';"))},
 done={"lib/temp.dart": '''double cToF(double c) => c * 9 / 5 + 32;

double fToC(double f) => (f - 32) * 5 / 9;

String describe(double c) {
  if (c.isNaN) throw ArgumentError('not a number');
  if (c < 0) return 'freezing';
  if (c < 10) return 'cold';
  if (c < 25) return 'mild';
  return 'hot';
}
'''}),
dict(id="cli-unit", text="Make bin/main.dart accept an optional --from f flag so that `main.dart --from f 212` treats the number as Fahrenheit and prints the Celsius value and description; without the flag behavior stays as it is.",
 partial={"lib/temp.dart": L, "bin/main.dart": ed(M, ("  final c = double.parse(args.first);", "  final fahrenheit = args.contains('--from');\n  final c = double.parse(args.last);"))},
 done={"bin/main.dart": '''import 'package:temp/temp.dart';

void main(List<String> args) {
  final fahrenheit = args.length >= 3 && args[0] == '--from' && args[1] == 'f';
  final value = double.parse(args.last);
  if (fahrenheit) {
    final c = fToC(value);
    print('${c.toStringAsFixed(1)} C, ${describe(c)}');
  } else {
    print('${cToF(value).toStringAsFixed(1)} F, ${describe(value)}');
  }
}
'''}),
])
