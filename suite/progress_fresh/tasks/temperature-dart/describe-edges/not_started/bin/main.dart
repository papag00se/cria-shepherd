// usage: dart run bin/main.dart <celsius>
import 'package:temp/temp.dart';

void main(List<String> args) {
  final c = double.parse(args.first);
  print('${cToF(c).toStringAsFixed(1)} F, ${describe(c)}');
}
