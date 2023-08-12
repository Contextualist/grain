package core

import (
	"sync"
	"time"

	"github.com/tinylib/msgp/msgp"
)

type (
	// Task is a function submitted with resource request
	Task struct {
		id    uint
		res   Resource
		rawFn msgp.Raw
	}
	// pendingTask is a running function holding a resource, with a deadline
	pendingTask struct {
		res     Resource
		rawFn   msgp.Raw
		timeout *time.Timer
	}

	pendingTaskMap struct {
		ch0 chan struct{}
		mu  sync.Mutex
		m   map[uint]pendingTask // id: pendingTask
	}

	taskPredicateFn func(uint) bool // predicate func for filtering task
)

func newPendingTaskMap() *pendingTaskMap {
	return &pendingTaskMap{
		ch0: make(chan struct{}),
		m:   make(map[uint]pendingTask),
	}
}

func (m *pendingTaskMap) Store(key uint, value pendingTask) {
	m.mu.Lock()
	m.m[key] = value
	m.mu.Unlock()
}

func (m *pendingTaskMap) LoadAndDelete(key uint) (*pendingTask, bool) {
	m.mu.Lock()
	pt, ok := m.m[key]
	if !ok {
		m.mu.Unlock()
		return nil, false
	}
	delete(m.m, key)
	if len(m.m) == 0 {
		select {
		case m.ch0 <- struct{}{}:
		default:
		}
	}
	m.mu.Unlock()
	if pt.timeout != nil {
		pt.timeout.Stop()
	}
	return &pt, true
}

func (m *pendingTaskMap) WaitEmpty() {
	m.mu.Lock()
	if len(m.m) == 0 {
		m.mu.Unlock()
		return
	}
	m.mu.Unlock()
	<-m.ch0
}
