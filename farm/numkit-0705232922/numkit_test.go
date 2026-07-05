package numkit

import (
	"fmt"
	"testing"
)

func TestGCD(t *testing.T) {
	tests := []struct {
		a, b, want int
	}{
		{8, 15, 1},
		{12, 18, 6},
		{0, 5, 5},
		{-12, 18, 6},
	}

	for _, tt := range tests {
		t.Run(fmt.Sprintf("GCD(%d,%d)", tt.a, tt.b), func(t *testing.T) {
			got := GCD(tt.a, tt.b)
			if got != tt.want {
				t.Errorf("GCD(%d, %d) = %d; want %d", tt.a, tt.b, got, tt.want)
			}
		})
	}
}

func TestClamp(t *testing.T) {
	tests := []struct {
		x, lo, hi, want int
	}{
		{-1, 0, 10, 0},
		{5, 0, 10, 5},
		{99, 0, 10, 10},
		{7, 10, 0, 7},
	}

	for _, tt := range tests {
		t.Run(fmt.Sprintf("Clamp(%d,%d,%d)", tt.x, tt.lo, tt.hi), func(t *testing.T) {
			got := Clamp(tt.x, tt.lo, tt.hi)
			if got != tt.want {
				t.Errorf("Clamp(%d, %d, %d) = %d; want %d", tt.x, tt.lo, tt.hi, got, tt.want)
			}
		})
	}
}
