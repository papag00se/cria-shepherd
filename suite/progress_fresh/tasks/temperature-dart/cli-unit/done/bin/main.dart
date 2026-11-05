import 'package:temp/temp.dart';

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
