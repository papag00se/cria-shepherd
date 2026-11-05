from suite.progress_fresh.dsl import ed

SEED = {
"go.mod": "module example.com/lru\n\ngo 1.22\n",
"lru.go": '''package lru

type entry struct {
	key string
	val int
}

// Cache is a fixed-capacity cache evicting the least recently used key.
type Cache struct {
	cap   int
	items []entry // index 0 is the most recently used
}

func New(cap int) *Cache { return &Cache{cap: cap} }

func (c *Cache) Get(key string) (int, bool) {
	for _, e := range c.items {
		if e.key == key {
			return e.val, true
		}
	}
	return 0, false
}

func (c *Cache) Put(key string, val int) {
	c.items = append([]entry{{key, val}}, c.items...)
	if len(c.items) > c.cap {
		c.items = c.items[:c.cap]
	}
}
''',
"lru_test.go": '''package lru

import "testing"

func TestEvictsOldest(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Put("c", 3)
	if _, ok := c.Get("a"); ok {
		t.Fatal("a should be evicted")
	}
}
''',
}
L = SEED["lru.go"]
T = SEED["lru_test.go"]
GET_NEW = '''func (c *Cache) Get(key string) (int, bool) {
	for i, e := range c.items {
		if e.key == key {
			copy(c.items[1:i+1], c.items[:i])
			c.items[0] = e
			return e.val, true
		}
	}
	return 0, false
}'''
GET_OLD = L[L.index("func (c *Cache) Get"):L.index("func (c *Cache) Put")].rstrip("\n")
PUT_OLD = L[L.index("func (c *Cache) Put"):].rstrip("\n")
PUT_NEW = '''func (c *Cache) Put(key string, val int) {
	for i, e := range c.items {
		if e.key == key {
			c.items = append(c.items[:i], c.items[i+1:]...)
			break
		}
	}
	c.items = append([]entry{{key, val}}, c.items...)
	if len(c.items) > c.cap {
		c.items = c.items[:c.cap]
	}
}'''
TASK = dict(extension=True, name="lrucache-go", language="Go", seed=SEED,
unrelated={"go.mod": SEED["go.mod"].replace("go 1.22", "go 1.23")},
reqs=[
dict(id="get-refreshes", text="Get should count as a use: reading a key makes it the most recently used so it survives the next eviction. Add a test showing that a key read before an overflowing Put is kept.",
 partial={"lru.go": ed(L, (GET_OLD, GET_NEW))},
 done={"lru.go": ed(L, (GET_OLD, GET_NEW)),
       "lru_test.go": T + '''
func TestGetRefreshesRecency(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Get("a")
	c.Put("c", 3)
	if _, ok := c.Get("a"); !ok {
		t.Fatal("a was read recently and must survive")
	}
	if _, ok := c.Get("b"); ok {
		t.Fatal("b should be evicted")
	}
}
'''}),
dict(id="put-overwrite", text="Putting an existing key must update its value and refresh its recency instead of storing a second copy of the key; add a test that checks Len stays correct after overwrites and add Len().",
 partial={"lru.go": ed(L, (PUT_OLD, PUT_NEW)) + "\nfunc (c *Cache) Len() int { return len(c.items) }\n"},
 done={"lru.go": ed(L, (PUT_OLD, PUT_NEW)) + "\nfunc (c *Cache) Len() int { return len(c.items) }\n",
       "lru_test.go": T + '''
func TestPutOverwrites(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("a", 9)
	if c.Len() != 1 {
		t.Fatalf("len = %d, want 1", c.Len())
	}
	if v, _ := c.Get("a"); v != 9 {
		t.Fatalf("a = %d, want 9", v)
	}
}
'''}),
dict(id="zero-cap", text="New(0) or a negative capacity should produce a cache that stores nothing (Put is a no-op, Get always misses) instead of panicking, and Delete(key) should remove a key and report whether it existed.",
 partial={"lru.go": ed(L, (PUT_OLD, "func (c *Cache) Put(key string, val int) {\n\tif c.cap <= 0 {\n\t\treturn\n\t}\n" + PUT_OLD.split("\n", 1)[1])) + '''
func (c *Cache) Delete(key string) bool {
	for i, e := range c.items {
		if e.key == key {
			c.items = append(c.items[:i], c.items[i+1:]...)
			return true
		}
	}
	return false
}
''', "lru_test.go": T + '''
func TestZeroCapacityStoresNothing(t *testing.T) {
	c := New(0)
	c.Put("a", 1)
	if _, ok := c.Get("a"); ok {
		t.Fatal("zero-capacity cache must not store")
	}
}
'''},
 done={"lru.go": ed(L, (PUT_OLD, "func (c *Cache) Put(key string, val int) {\n\tif c.cap <= 0 {\n\t\treturn\n\t}\n" + PUT_OLD.split("\n", 1)[1])) + '''
func (c *Cache) Delete(key string) bool {
	for i, e := range c.items {
		if e.key == key {
			c.items = append(c.items[:i], c.items[i+1:]...)
			return true
		}
	}
	return false
}
''', "lru_test.go": T + '''
func TestZeroCapacityStoresNothing(t *testing.T) {
	c := New(0)
	c.Put("a", 1)
	if _, ok := c.Get("a"); ok {
		t.Fatal("zero-capacity cache must not store")
	}
}

func TestDelete(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	if !c.Delete("a") || c.Delete("a") {
		t.Fatal("Delete should report presence exactly once")
	}
}
'''}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["get-refreshes"]["lru_test.go"] = T + '''
func TestGetReturnsStoredValue(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	if v, ok := c.Get("a"); !ok || v != 1 {
		t.Fatalf("Get(a) = %d, %v", v, ok)
	}
}
'''
_P["put-overwrite"]["lru_test.go"] = T + '''
func TestPutOverwritesValue(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("a", 9)
	if v, _ := c.Get("a"); v != 9 {
		t.Fatalf("a = %d, want 9", v)
	}
}
'''
