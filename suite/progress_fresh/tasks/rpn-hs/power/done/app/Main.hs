import Rpn

main :: IO ()
main = interact (\s -> show (evalRpn s) ++ "\n")
