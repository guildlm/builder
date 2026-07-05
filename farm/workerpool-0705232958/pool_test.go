package pool

import (
	"sync/atomic"
	"testing"
)

func TestParallelMapOrderAndCount(t *testing.T) {
	in := []int{1, 2, 3, 4, 5, 6, 7, 8}
	var calls int64
	got := ParallelMap(in, 3, func(x int) int {
		atomic.AddInt64(&calls, 1)
		return x * x
	})
	want := []int{1, 4, 9, 16, 25, 36, 49, 64}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got[%d] = %d, want %d", i, got[i], want[i])
		}
	}
	if calls != int64(len(in)) {
		t.Fatalf("fn called %d times, want %d", calls, len(in))
	}
}

func TestParallelMapZeroWorkers(t *testing.T) {
	got := ParallelMap([]int{2, 3}, 0, func(x int) int { return x + 1 })
	if len(got) != 2 || got[0] != 3 || got[1] != 4 {
		t.Fatalf("got %v, want [3 4]", got)
	}
}
