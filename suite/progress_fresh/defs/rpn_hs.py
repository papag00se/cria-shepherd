from suite.progress_fresh.dsl import ed

SEED = {
"src/Rpn.hs": '''module Rpn (evalRpn) where

evalRpn :: String -> Double
evalRpn = head . foldl step [] . words
  where
    step (y:x:rest) "+" = x + y : rest
    step (y:x:rest) "-" = x - y : rest
    step (y:x:rest) "*" = x * y : rest
    step st tok = read tok : st
''',
"test/Spec.hs": '''import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == 14)
''',
"app/Main.hs": '''import Rpn

main :: IO ()
main = interact (\\s -> show (evalRpn s) ++ "\\n")
''',
}
R = SEED["src/Rpn.hs"]
S = SEED["test/Spec.hs"]
TASK = dict(extension=True, name="rpn-hs", language="Haskell", seed=SEED,
unrelated={"app/Main.hs": "-- reads one RPN expression from stdin\n" + SEED["app/Main.hs"]},
reqs=[
dict(id="divide", text="Add the / operator to evalRpn and make it return a Left error message instead of Infinity when dividing by zero.",
 partial={"src/Rpn.hs": '''module Rpn (evalRpn) where

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
'''},
 done={"src/Rpn.hs": '''module Rpn (evalRpn) where

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
''',
  "test/Spec.hs": '''import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == Right 14)
  print (evalRpn "8 2 /" == Right 4)
  print (evalRpn "1 0 /" == Left "division by zero")
''',
  "app/Main.hs": '''import Rpn

main :: IO ()
main = interact (\\s -> either ("error: " ++) show (evalRpn s) ++ "\\n")
'''}),
dict(id="malformed", text="evalRpn crashes with a pattern-match error on input such as \"+\" or \"1 2\" (too few or too many values). Return a Left error for malformed expressions instead, and test both shapes.", ns=True,
 partial={"src/Rpn.hs": '''module Rpn (evalRpn) where

evalRpn :: String -> Either String Double
evalRpn s = case foldl step [] (words s) of
  [x] -> Right x
  _ -> Left "malformed expression"
  where
    step (y:x:rest) "+" = x + y : rest
    step (y:x:rest) "-" = x - y : rest
    step (y:x:rest) "*" = x * y : rest
    step st tok = read tok : st
''', "test/Spec.hs": '''import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "1 2" == Left "malformed expression")
'''},
 done={"src/Rpn.hs": '''module Rpn (evalRpn) where

evalRpn :: String -> Either String Double
evalRpn s = go [] (words s)
  where
    go [x] [] = Right x
    go _ [] = Left "malformed expression"
    go (y:x:rest) ("+":ts) = go (x + y : rest) ts
    go (y:x:rest) ("-":ts) = go (x - y : rest) ts
    go (y:x:rest) ("*":ts) = go (x * y : rest) ts
    go _ (t:_) | t `elem` ["+", "-", "*"] = Left "malformed expression"
    go st (t:ts) = go (read t : st) ts
''', "test/Spec.hs": '''import Rpn

main :: IO ()
main = do
  print (evalRpn "3 4 +" == Right 7)
  print (evalRpn "5 1 2 + 4 * + 3 -" == Right 14)
  print (evalRpn "+" == Left "malformed expression")
  print (evalRpn "1 2" == Left "malformed expression")
''', "app/Main.hs": '''import Rpn

main :: IO ()
main = interact (\\s -> either ("error: " ++) show (evalRpn s) ++ "\\n")
'''}),
dict(id="power",  text="Add a ^ (power) operator and a unary 'neg' token to evalRpn, and cover both in test/Spec.hs.",
 partial={"src/Rpn.hs": ed(R, ("    step st tok", "    step (y:x:rest) \"^\" = x ** y : rest\n    step (x:rest) \"neg\" = negate x : rest\n    step st tok"))},
 done={"src/Rpn.hs": ed(R, ("    step st tok", "    step (y:x:rest) \"^\" = x ** y : rest\n    step (x:rest) \"neg\" = negate x : rest\n    step st tok")),
       "test/Spec.hs": S + "  print (evalRpn \"2 10 ^\" == 1024)\n  print (evalRpn \"5 neg 2 +\" == -3)\n"}),
])
