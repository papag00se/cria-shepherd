package lru

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
	for i, e := range c.items {
		if e.key == key {
			copy(c.items[1:i+1], c.items[:i])
			c.items[0] = e
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
