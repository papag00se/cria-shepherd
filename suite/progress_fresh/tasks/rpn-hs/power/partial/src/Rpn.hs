module Rpn (evalRpn) where

evalRpn :: String -> Double
evalRpn = head . foldl step [] . words
  where
    step (y:x:rest) "+" = x + y : rest
    step (y:x:rest) "-" = x - y : rest
    step (y:x:rest) "*" = x * y : rest
    step (y:x:rest) "^" = x ** y : rest
    step (x:rest) "neg" = negate x : rest
    step st tok = read tok : st
