import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == 14)
