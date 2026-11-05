import 'package:temp/temp.dart';
import 'package:test/test.dart';

void main() {
  test('cToF', () => expect(cToF(100), 212));
  test('fToC', () => expect(fToC(32), 0));
}
