-- reads one RPN expression from stdin
import Rpn

main :: IO ()
main = interact (\s -> show (evalRpn s) ++ "\n")
