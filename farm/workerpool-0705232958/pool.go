package pool

import "sync"

// ParallelMap applies fn to every item using at most workers goroutines and
// returns the results in input order. workers <= 0 is treated as 1. It is
// race-free: each worker writes only its own output slot, so no mutex guards
// the results slice.
func ParallelMap[T any, R any](items []T, workers int, fn func(T) R) []R {
	if workers < 1 {
		workers = 1
	}
	results := make([]R, len(items))
	jobs := make(chan int)

	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				results[i] = fn(items[i])
			}
		}()
	}
	for i := range items {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	return results
}
