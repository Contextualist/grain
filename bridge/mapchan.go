package main

import (
	"sync"
)

type mapChan[T any] struct {
	_m map[string]chan T
	sync.Mutex
	fac func() chan T
}

func newMapChan[T any](fac func() chan T) *mapChan[T] {
	return &mapChan[T]{_m: make(map[string]chan T), fac: fac}
}

func (m *mapChan[T]) Get(k string) chan T {
	m.Lock()
	defer m.Unlock()
	if v, ok := m._m[k]; ok {
		return v
	}
	m._m[k] = m.fac()
	return m._m[k]
}

func (m *mapChan[T]) Delete(k string) {
	m.Lock()
	delete(m._m, k)
	m.Unlock()
}

var (
	subd2head = newMapChan(func() chan []byte { return make(chan []byte, 1) })
	head2subd = newMapChan(func() chan []byte { return make(chan []byte, 1) })
	relays    = newMapChan(func() chan struct{} { return make(chan struct{}, 0) })
	backlogs  = newMapChan(func() chan struct{} {
		ch := make(chan struct{}, *loadBal)
		for i := 0; i < *loadBal; i++ {
			ch <- struct{}{}
		}
		return ch
	})
)
