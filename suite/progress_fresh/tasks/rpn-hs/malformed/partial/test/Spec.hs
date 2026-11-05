import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "1 2" == Left "malformed expression")
