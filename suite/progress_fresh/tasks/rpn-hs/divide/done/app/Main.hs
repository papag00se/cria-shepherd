import Rpn

main :: IO ()
main = interact (\s -> either ("error: " ++) show (evalRpn s) ++ "\n")
