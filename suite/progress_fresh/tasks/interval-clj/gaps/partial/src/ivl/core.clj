(ns ivl.core)

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

(defn gaps [ivs]
  (let [m (sort-by first ivs)]
    (vec (map (fn [[_ b] [a _]] [b a]) m (rest m)))))
