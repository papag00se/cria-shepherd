module Rpn (evalRpn) where

evalRpn :: String -> Either String Double
evalRpn s = case foldl step [] (words s) of
  [x] -> Right x
  _ -> Left "malformed expression"
  where
    step (y:x:rest) "+" = x + y : rest
    step (y:x:rest) "-" = x - y : rest
    step (y:x:rest) "*" = x * y : rest
    step st tok = read tok : st
