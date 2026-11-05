module Rpn (evalRpn) where

evalRpn :: String -> Either String Double
evalRpn s = go [] (words s)
  where
    go [x] [] = Right x
    go _ [] = Left "malformed expression"
    go (y:x:rest) ("+":ts) = go (x + y : rest) ts
    go (y:x:rest) ("-":ts) = go (x - y : rest) ts
    go (y:x:rest) ("*":ts) = go (x * y : rest) ts
    go (y:x:rest) ("/":ts)
      | y == 0 = Left "division by zero"
      | otherwise = go (x / y : rest) ts
    go st (t:ts) = go (read t : st) ts
