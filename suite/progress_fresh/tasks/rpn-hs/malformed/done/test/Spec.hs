import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == Right 14)
  print (evalRpn "+" == Left "malformed expression")
  print (evalRpn "1 2" == Left "malformed expression")
