import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == 14)
  print (evalRpn "2 10 ^" == 1024)
  print (evalRpn "5 neg 2 +" == -3)
