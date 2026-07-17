"""The static self-deadlock gate: flag a method that re-locks a mutex it already
holds via a deferred unlock, and — the harder half — flag NOTHING else.

Motivated by shortener 2026-07-17: Resolve() = RLock(); defer RUnlock(); Lock().
A read lock cannot be upgraded to a write lock on the same RWMutex, so it blocks
forever, a test timeout the compiler never sees. An A/B proved prompt wording does
not stop the model writing it, so it became a check. A check that rejects correct
code is worse than none, so the negatives here carry as much weight as the one
positive.
"""
from src.builder import mutex_self_deadlock, _is_clean, GoToolchain

TC = GoToolchain()

# The exact shipped bug: read-lock, defer the read-unlock, then take the write
# lock while still holding the read lock.
DEADLOCK = """package main
func (s *MemStore) Resolve(code string) (Link, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	link, ok := s.links[code]
	if !ok {
		return Link{}, ErrNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	link.Hits++
	s.links[code] = link
	return link, nil
}
"""

# The correct rewrite: one Lock at the top, because Resolve mutates Hits.
SINGLE_LOCK = """package main
func (s *MemStore) Resolve(code string) (Link, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	link, ok := s.links[code]
	if !ok {
		return Link{}, ErrNotFound
	}
	link.Hits++
	s.links[code] = link
	return link, nil
}
"""

# A read-only accessor: RLock, defer RUnlock, no second acquire. The overwhelming
# common case, and it must stay clean.
READ_ONLY = """package main
func (s *MemStore) Stats(code string) (Link, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	l, ok := s.links[code]
	if !ok {
		return Link{}, ErrNotFound
	}
	return l, nil
}
"""

# Two SEPARATE methods each locking once. The lock name repeats across the file
# but never nests within one body — not a deadlock, and the gate must not be
# fooled by a whole-file count.
TWO_METHODS = """package main
func (s *MemStore) Save(u string) Link {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.put(u)
}
func (s *MemStore) Get(c string) (Link, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	l, ok := s.links[c]
	return l, ok
}
"""

# Sequential lock / unlock / lock in one body — no defer holding the first, so the
# second acquire is not nested. Rare, but it must not trip the deferred-only rule.
SEQUENTIAL = """package main
func (s *MemStore) Rotate() {
	s.mu.Lock()
	s.a++
	s.mu.Unlock()
	s.mu.Lock()
	s.b++
	s.mu.Unlock()
}
"""


def test_flags_the_shipped_deadlock():
    assert mutex_self_deadlock(DEADLOCK) == {"Resolve"}
    assert not _is_clean(DEADLOCK, True, TC)


def test_single_lock_is_clean():
    assert mutex_self_deadlock(SINGLE_LOCK) == set()
    assert _is_clean(SINGLE_LOCK, True, TC)


def test_read_only_accessor_is_clean():
    assert mutex_self_deadlock(READ_ONLY) == set()


def test_two_methods_locking_once_each_is_clean():
    # The false positive a whole-file lock count would produce.
    assert mutex_self_deadlock(TWO_METHODS) == set()


def test_sequential_lock_unlock_lock_is_clean():
    # No deferred hold on the first acquire, so the second is not nested.
    assert mutex_self_deadlock(SEQUENTIAL) == set()


def test_non_go_is_ignored_by_is_clean():
    assert _is_clean(DEADLOCK, False, TC)
