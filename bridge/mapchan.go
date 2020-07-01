package main

import (
	"sync"
)

type _m map[string]interface{}
type mapChan struct {
	_m
	sync.Mutex
	fac func() interface{}
}

func newMapChan(fac func() interface{}) *mapChan {
	return &mapChan{_m: make(_m), fac: fac}
}

func (m *mapChan) Get(k string) interface{} {
	m.Lock()
	defer m.Unlock()
	if v, ok := m._m[k]; ok {
		return v
	}
	m._m[k] = m.fac()
	return m._m[k]
}

func (m *mapChan) Delete(k string) {
	m.Lock()
	delete(m._m, k)
	m.Unlock()
}

var (
	subd2head = newMapChan(func() interface{} { return make(chan []byte, 1) })
	head2subd = newMapChan(func() interface{} { return make(chan []byte, 1) })
	relays    = newMapChan(func() interface{} { return make(chan struct{}, 0) })
	backlogs  = newMapChan(func() interface{} {
		ch := make(chan struct{}, *loadBal)
		for i := 0; i < *loadBal; i++ {
			ch <- struct{}{}
		}
		return ch
	})
)
