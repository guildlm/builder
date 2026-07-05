package numkit

import "math"

// GCD returns the greatest common divisor of the absolute values of a and b using the Euclidean algorithm.
// GCD(0,0) is 0.
func GCD(a, b int) int {
	if a == 0 && b == 0 {
		return 0
	}
	return int(math.Abs(float64(euclideanGCD(abs(a), abs(b)))))
}

// Clamp returns x bounded to the inclusive range [lo, hi]; if lo > hi the function returns x unchanged.
func Clamp(x, lo, hi int) int {
	if lo > hi {
		return x
	}
	if x < lo {
		return lo
	}
	if x > hi {
		return hi
	}
	return x
}

// Helper function to calculate the Euclidean GCD
func euclideanGCD(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}

// Helper function to calculate the absolute value
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
