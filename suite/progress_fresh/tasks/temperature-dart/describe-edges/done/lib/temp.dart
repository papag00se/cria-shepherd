double cToF(double c) => c * 9 / 5 + 32;

double fToC(double f) => (f - 32) * 5 / 9;

String describe(double c) {
  if (c.isNaN) throw ArgumentError('not a number');
  if (c < 0) return 'freezing';
  if (c < 10) return 'cold';
  if (c < 25) return 'mild';
  return 'hot';
}
