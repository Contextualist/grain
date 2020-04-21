package main

import (
	"sync"
)

type _m map[string]chan []byte
type mapChan struct {
	_m
	sync.Mutex
	bufferCap int
}

func newMapChan(bc int) *mapChan {
	return &mapChan{_m: make(_m), bufferCap: bc}
}

func (m *mapChan) Get(k string) chan []byte {
	m.Lock()
	defer m.Unlock()
	if v, ok := m._m[k]; ok {
		return v
	}
	m._m[k] = make(chan []byte, m.bufferCap)
	return m._m[k]
}

func (m *mapChan) Delete(k string) {
	m.Lock()
	delete(m._m, k)
	m.Unlock()
}

var (
	subd2head = newMapChan(1)
	head2subd = newMapChan(1)
	relays    = newMapChan(0)
)
