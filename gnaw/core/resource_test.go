package core

import (
	"testing"
)

func assertEq(t *testing.T, a interface{}, b interface{}) {
	if a != b {
		t.Fatalf("%s != %s", a, b)
	}
}

func TestMemory(t *testing.T) {
	assertEq(t, Memory(16).String(), "Memory(16GB)")

	m0 := Memory(64)
	_, ok := m0.Alloc(Memory(65))
	assertEq(t, ok, false)
	a, ok := m0.Alloc(Memory(16))
	assertEq(t, ok, true)
	assertEq(t, a.String(), "Memory(16GB)")
	assertEq(t, m0.String(), "Memory(48GB)")

	m0.Dealloc(a)
	assertEq(t, m0.String(), "Memory(64GB)")
}

func TestCores(t *testing.T) {
	assertEq(t, Cores(uint(3)).String(), "Cores([0-2])")
	assertEq(t, Cores([]uint{5, 7, 8}).String(), "Cores([5,7-8])")

	c0 := Cores(uint(4))
	_, ok := c0.Alloc(Cores(uint(5)))
	assertEq(t, ok, false)
	a, ok := c0.Alloc(Cores(uint(3)))
	assertEq(t, ok, true)
	assertEq(t, a.String(), "Cores([1-3])") // current implentation takes from tail
	assertEq(t, c0.String(), "Cores([0])")

	c0.Dealloc(a)
	assertEq(t, c0.String(), "Cores([0-3])")
}

func TestWTime(t *testing.T) {
	assertEq(t, WTime(7000, 0, false).String(), "Walltime(01:56:40)")
	assertEq(t, WTime(7000, 0, true).String(), "Walltime(01:56:39)")

	t0 := WTime(30, 0, true)
	_, ok := t0.Alloc(WTime(31, 0, false))
	assertEq(t, ok, false)
	a, ok := t0.Alloc(WTime(3, 0, false))
	assertEq(t, ok, true)
	assertEq(t, a.String(), "Walltime(00:00:03)")
}

func TestMultiResource(t *testing.T) {
	assertEq(t, And(Cores(uint(3)), Memory(16)).String(), "Cores([0-2]) & Memory(16GB)")

	r := And(Cores(uint(6)), Memory(16))
	_, ok := r.Alloc(And(Cores(uint(9))))
	assertEq(t, ok, false)
	_, ok = r.Alloc(And(Cores(uint(3)), Memory(17)))
	assertEq(t, ok, false)
	_, ok = r.Alloc(And(Cores(uint(3)), Memory(9), WTime(0, 0, false)))
	assertEq(t, ok, false)
	a, ok := r.Alloc(And(Cores(uint(3)), Memory(9)))
	assertEq(t, ok, true)
	assertEq(t, a.String(), "Cores([3-5]) & Memory(9GB)")
	assertEq(t, r.String(), "Cores([0-2]) & Memory(7GB)")

	r.Dealloc(a)
	assertEq(t, r.String(), "Cores([0-5]) & Memory(16GB)")
}
