from suite.progress_fresh.dsl import ed

SEED = {
"src/ivl/core.clj": '''(ns ivl.core)

(defn overlaps? [[a1 b1] [a2 b2]]
  (and (<= a1 b2) (<= a2 b1)))

(defn merge-intervals [ivs]
  (reduce (fn [acc [a b]]
            (let [[la lb] (peek acc)]
              (if (and la (<= a lb))
                (conj (pop acc) [la b])
                (conj acc [a b]))))
          []
          (sort-by first ivs)))
''',
"test/ivl/core_test.clj": '''(ns ivl.core-test
  (:require [clojure.test :refer :all]
            [ivl.core :refer :all]))

(deftest overlap
  (is (overlaps? [1 5] [4 8]))
  (is (not (overlaps? [1 2] [3 4]))))

(deftest merging
  (is (= [[1 8]] (merge-intervals [[1 5] [4 8]]))))
''',
}
C = SEED["src/ivl/core.clj"]
T = SEED["test/ivl/core_test.clj"]
TASK = dict(extension=True, name="interval-clj", language="Clojure", seed=SEED,
unrelated={"src/ivl/core.clj": C.replace("(defn overlaps?", ";; closed intervals [start end]\n(defn overlaps?")},
reqs=[
dict(id="merge-contained", text="merge-intervals is wrong when one interval is fully inside another ([1 10] and [2 3] should merge to [[1 10]], not [[1 3]]). Fix it and add that case as a test.",
 partial={"src/ivl/core.clj": ed(C, ("(conj (pop acc) [la b])", "(conj (pop acc) [la (max lb b)])"))},
 done={"src/ivl/core.clj": ed(C, ("(conj (pop acc) [la b])", "(conj (pop acc) [la (max lb b)])")),
       "test/ivl/core_test.clj": ed(T, ("(is (= [[1 8]] (merge-intervals [[1 5] [4 8]]))))", "(is (= [[1 8]] (merge-intervals [[1 5] [4 8]])))\n  (is (= [[1 10]] (merge-intervals [[1 10] [2 3]]))))"))}),
dict(id="gaps", text="Add (gaps ivs) returning the uncovered [start end] spans between the merged intervals, in order (empty for zero or one merged interval), with tests.",
 partial={"src/ivl/core.clj": C + "\n(defn gaps [ivs]\n  (let [m (sort-by first ivs)]\n    (vec (map (fn [[_ b] [a _]] [b a]) m (rest m)))))\n"},
 done={"src/ivl/core.clj": C + "\n(defn gaps [ivs]\n  (let [m (merge-intervals ivs)]\n    (vec (map (fn [[_ b] [a _]] [b a]) m (rest m)))))\n",
       "test/ivl/core_test.clj": T + "\n(deftest gap-finding\n  (is (= [[5 7] [9 12]] (gaps [[1 5] [7 9] [12 14]])))\n  (is (= [] (gaps [[1 5]])))\n  (is (= [] (gaps []))))\n"}),
dict(id="total-length", text="Add (covered-length ivs) returning the total length covered by the union of the intervals (overlaps counted once) and a test where intervals overlap.",
 partial={"src/ivl/core.clj": C + "\n(defn covered-length [ivs]\n  (reduce + (map (fn [[a b]] (- b a)) ivs)))\n"},
 done={"src/ivl/core.clj": C + "\n(defn covered-length [ivs]\n  (reduce + (map (fn [[a b]] (- b a)) (merge-intervals ivs))))\n",
       "test/ivl/core_test.clj": T + "\n(deftest covered\n  (is (= 7 (covered-length [[1 5] [4 8]])))\n  (is (= 0 (covered-length []))))\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["gaps"]["test/ivl/core_test.clj"] = T + "\n(deftest gap-finding\n  (is (= [[5 7] [9 12]] (gaps [[1 5] [7 9] [12 14]]))))\n"
_P["total-length"]["test/ivl/core_test.clj"] = T + "\n(deftest covered\n  (is (= 6 (covered-length [[1 5] [7 9]]))))\n"
