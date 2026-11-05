import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == Right 14)
  print (evalRpn "8 2 /" == Right 4)
  print (evalRpn "1 0 /" == Left "division by zero")
