package core

import (
	"sync"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog/log"
)

type (
	RemoteBase struct {
		name    string
		res     Resource
		closing bool
		health  int64

		retryq  chan<- Task
		resultq chan<- ResultMsg // won't be used if nil
		mgr     ResourceManager
		pending *pendingTaskMap

		chInput       chan Task
		closeSendOnce sync.Once
		sendQuit      chan struct{}
		recvQuit      chan struct{}
	}

	IRemote interface {
		// to be implemented
		sendLoop()
		recvLoop()
		batchCancel(taskPredicateFn)
		close()

		// implemented by RemoteBase
		closeSend()
		// implemented by RemoteBase (get/set)
		getName() string
		getRes() Resource
		getPending() *pendingTaskMap
		getInput() chan Task
		isClosing() bool
		setClosing()
	}

	ResourceManager interface {
		dealloc(IRemote, Resource)
		unregister(string)
	}
)

func newRemoteBase(name string, res Resource, mgr ResourceManager, retryq chan<- Task, resultq chan<- ResultMsg) *RemoteBase {
	return &RemoteBase{
		name:     name,
		res:      res,
		health:   FULL_HEALTH,
		mgr:      mgr,
		retryq:   retryq,
		resultq:  resultq,
		pending:  newPendingTaskMap(),
		chInput:  make(chan Task, 16),
		sendQuit: make(chan struct{}),
		recvQuit: make(chan struct{}),
	}
}

func (w *RemoteBase) predispatch(t Task) {
	var timeout *time.Timer
	if wt, ok := t.res.(*multiResource).resm["WTime"]; ok { // NOTE: assumed multiResource
		tid := t.id
		timeout = time.AfterFunc(wt.(*wtime).t+3*time.Minute, func() {
			pt, ok := w.pending.LoadAndDelete(tid)
			if !ok { // in rare cases, we receive the result right after this timeout get triggered
				return
			}
			atomic.AddUint64(&DefaultStat.lostOrLateResponse, 1)
			log.Debug().Uint("tid", tid).Msg("resubmit due to 3 min pass timeout")
			w.resubmit(tid, pt)
		})
	}
	w.pending.Store(t.id, pendingTask{t.res, t.rawFn, timeout})
}

func (w *RemoteBase) postreceive(r ResultMsg) {
	pt, ok := w.pending.LoadAndDelete(r.Tid)
	if !ok { // has been resubmmitted by the pending task's local timeout (pt.timeout)
		atomic.AddUint64(&DefaultStat.lateResponse, 1)
		log.Info().Str("wname", w.name).Uint("tid", r.Tid).Msg("Remote.recvLoop: received phantom job's result")
		return
	}
	switch r.Exception {
	case "":
		atomic.AddUint64(&DefaultStat.completed, 1)
		atomic.StoreInt64(&w.health, FULL_HEALTH)
		if w.resultq != nil {
			w.resultq <- r
		}
		w.mgr.dealloc(w, pt.res)
	case "UserCancelled":
		atomic.AddUint64(&DefaultStat.exception, 1)
		w.mgr.dealloc(w, pt.res) // sink task if it is cancelled by user
	default:
		atomic.AddUint64(&DefaultStat.exception, 1)
		log.Debug().Uint("tid", r.Tid).Msg("resubmit due to exception")
		if w.resultq != nil {
			w.resultq <- r // notify back exception while handling resubmit
		}
		w.resubmit(r.Tid, pt)
	}

}

func (w *RemoteBase) resubmit(tid uint, pt *pendingTask) {
	w.health_dec(1)
	w.retryq <- Task{tid, pt.res, pt.rawFn}
	w.mgr.dealloc(w, pt.res)
}

func (w *RemoteBase) closeSend() {
	w.closeSendOnce.Do(func() {
		close(w.chInput)
		<-w.sendQuit
	})
}

func (w *RemoteBase) ejectPending() {
	w.pending.mu.Lock()
	for tid, pt := range w.pending.m {
		if pt.timeout != nil {
			pt.timeout.Stop()
		}
		w.retryq <- Task{tid, pt.res, pt.rawFn}
	}
	w.pending.m = nil
	w.pending.mu.Unlock()
	for t := range w.chInput {
		w.retryq <- t
	}
}

func (w *RemoteBase) health_dec(v int64) {
	if w.closing || atomic.AddInt64(&w.health, -v) > 0 {
		return
	}
	log.Warn().Str("wname", w.name).Msg("Quit worker due to poor health")
	w.mgr.unregister(w.name)
}

func (w *RemoteBase) sendLoop()                     { panic("sendLoop is not implemented!") }
func (w *RemoteBase) recvLoop()                     { panic("recvLoop is not implemented!") }
func (w *RemoteBase) batchCancel(_ taskPredicateFn) { panic("batchCancel is not implemented!") }
func (w *RemoteBase) close()                        { panic("close is not implemented!") }

func (w *RemoteBase) getName() string             { return w.name }
func (w *RemoteBase) getRes() Resource            { return w.res }
func (w *RemoteBase) getPending() *pendingTaskMap { return w.pending }
func (w *RemoteBase) getInput() chan Task         { return w.chInput }
func (w *RemoteBase) isClosing() bool             { return w.closing }
func (w *RemoteBase) setClosing()                 { w.closing = true }
