import 'package:temp/temp.dart';

void main(List<String> args) {
  final fahrenheit = args.contains('--from');
  final c = double.parse(args.last);
  print('${cToF(c).toStringAsFixed(1)} F, ${describe(c)}');
}
