(ns ivl.core-test
  (:require [clojure.test :refer :all]
            [ivl.core :refer :all]))

(deftest overlap
  (is (overlaps? [1 5] [4 8]))
  (is (not (overlaps? [1 2] [3 4]))))

(deftest merging
  (is (= [[1 8]] (merge-intervals [[1 5] [4 8]]))))

(deftest gap-finding
  (is (= [[5 7] [9 12]] (gaps [[1 5] [7 9] [12 14]]))))
