package core

import (
	"net"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

const (
	FULL_HEALTH         = 3
	HEARTBEAT_INTERVAL  = 10 * time.Second
	HEARTBEAT_TOLERANCE = 3
)

type (
	RemoteBase struct {
		name    string
		res     Resource
		closing atomic.Bool
		health  atomic.Int64

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
	r := &RemoteBase{
		name:     name,
		res:      res,
		mgr:      mgr,
		retryq:   retryq,
		resultq:  resultq,
		pending:  newPendingTaskMap(),
		chInput:  make(chan Task, 16),
		sendQuit: make(chan struct{}),
		recvQuit: make(chan struct{}),
	}
	r.health.Store(FULL_HEALTH)
	return r
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
			DefaultStat.lostOrLateResponse.Add(1)
			log.Debug().Uint("tid", tid).Msg("resubmit due to 3 min pass timeout")
			w.resubmit(tid, pt)
		})
	}
	w.pending.Store(t.id, pendingTask{t.res, t.rawFn, timeout})
}

func (w *RemoteBase) postreceive(r ResultMsg) {
	pt, ok := w.pending.LoadAndDelete(r.Tid)
	if !ok { // has been resubmmitted by the pending task's local timeout (pt.timeout)
		DefaultStat.lateResponse.Add(1)
		log.Info().Str("wname", w.name).Uint("tid", r.Tid).Msg("RemoteBase.postreceive: received phantom job's result")
		return
	}
	switch r.Exception {
	case "":
		DefaultStat.completed.Add(1)
		w.health.Store(FULL_HEALTH)
		if w.resultq != nil {
			w.resultq <- r
		}
		w.mgr.dealloc(w, pt.res)
	case "UserCancelled":
		DefaultStat.exception.Add(1)
		w.mgr.dealloc(w, pt.res) // sink task if it is cancelled by user
	default:
		DefaultStat.exception.Add(1)
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
	if w.isClosing() || w.health.Add(-v) > 0 {
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
func (w *RemoteBase) isClosing() bool             { return w.closing.Load() }
func (w *RemoteBase) setClosing()                 { w.closing.Store(true) }

type (
	// A Remote sends functions to its worker and watch for their results
	Remote struct {
		*RemoteBase

		mu       sync.Mutex
		conn     net.Conn
		receiver *msgp.Reader
	}
)

func newRemote(name string, res Resource, mgr ResourceManager, retryq chan<- Task, resultq chan<- ResultMsg, conn net.Conn, rcv *msgp.Reader) *Remote {
	base := newRemoteBase(name, res, mgr, retryq, resultq)
	return &Remote{
		RemoteBase: base,
		conn:       conn,
		receiver:   rcv,
	}
}

func (w *Remote) sendLoop() {
	defer func() { close(w.sendQuit) }()
	sender := msgp.NewWriter(w.conn)
	go func() {
		t := time.NewTicker(HEARTBEAT_INTERVAL)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				w.mu.Lock()
				_ = (&ControlMsg{Cmd: "HBT"}).EncodeMsg(sender)
				_ = sender.Flush()
				w.mu.Unlock()
			case <-w.recvQuit: // heartbeat is still needed after closeSend
				return
			}
		}
	}()
	// Buffered channel `w.chInput` for:
	// 1. Relieving outbound network backpressure
	// 2. Reducing lock contention
	for t := range w.chInput {
		w.predispatch(t)

		w.mu.Lock()
		err := (&FnMsg{t.id, resToMsg(t.res), t.rawFn}).EncodeMsg(sender)
		if err != nil {
			w.health_dec(FULL_HEALTH)
			w.mu.Unlock()
			return
		}
		err = sender.Flush()
		if err != nil {
			w.health_dec(FULL_HEALTH)
			w.mu.Unlock()
			return
		}
		w.mu.Unlock()
	}
}

// pass on the result or request a retry; notify resource management
func (w *Remote) recvLoop() {
	defer func() { close(w.recvQuit) }()
	var trafficFlag atomic.Bool
	go func() {
		t := time.NewTicker(HEARTBEAT_INTERVAL * HEARTBEAT_TOLERANCE)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				if trafficFlag.CompareAndSwap(true, false) {
					continue
				}
				log.Warn().Str("wname", w.name).Msg("Remote.recvLoop: heartbeat response timeout")
				w.health_dec(FULL_HEALTH)
				return
			case <-w.recvQuit:
				return
			}
		}
	}()
	for {
		var r ResultMsg
		err := r.DecodeMsg(w.receiver)
		if err != nil {
			if !w.isClosing() {
				log.Error().Str("wname", w.name).Err(err).Msg("Remote.recvLoop: read error")
				w.health_dec(FULL_HEALTH)
			}
			return
		}
		trafficFlag.Store(true)
		if r.Tid == 0 { // assume to be heartbeat response
			continue
		}

		w.postreceive(r)
	}
}

// request worker to cancel certain running tasks; those tasks will return a UserCancelled status and not be resubmitted
func (w *Remote) batchCancel(pred taskPredicateFn) {
	w.pending.mu.Lock()
	var tids []string
	for tid := range w.pending.m {
		if !pred(tid) {
			tids = append(tids, strconv.Itoa(int(tid)))
		}
	}
	w.pending.mu.Unlock()
	if len(tids) == 0 {
		return
	}
	tidsStr := strings.Join(tids, ",")

	can, _ := (&ControlMsg{Cmd: "CAN", Name: &tidsStr}).MarshalMsg(nil)
	w.mu.Lock()
	_, _ = w.conn.Write(can)
	w.mu.Unlock()
}

func (w *Remote) close() {
	// assume that w.chInput will not be passed in data during and after
	// this function call
	w.setClosing()
	bye, _ := (&ControlMsg{Cmd: "FIN"}).MarshalMsg(nil)
	w.mu.Lock()
	_, _ = w.conn.Write(bye)
	w.mu.Unlock()

	w.closeSend()
	select {
	case <-w.recvQuit:
	case <-time.After(HEARTBEAT_INTERVAL * HEARTBEAT_TOLERANCE):
	}
	w.mu.Lock()
	_ = w.conn.Close()
	w.mu.Unlock()
	// migrate all pending tasks once the pending gets stable
	w.ejectPending()
}

type (
	SpecializedRemote struct {
		*RemoteBase

		// to notify that the task with corresponding tid can be executed
		approvalq chan<- FnMsg
		// to receive the execution result status of a task
		chRStatus <-chan ResultMsg
		// unregister self from an external listing
		unregister func()
		// optional connection for control only
		mu   sync.Mutex
		conn net.Conn
	}
)

func newSpecializedRemote(
	name string, res Resource, mgr ResourceManager, retryq chan<- Task, conn net.Conn,
	approvalq chan<- FnMsg, chRStatus <-chan ResultMsg, unregister func(),
) *SpecializedRemote {
	base := newRemoteBase(name, res, mgr, retryq, nil)
	return &SpecializedRemote{
		RemoteBase: base,
		approvalq:  approvalq,
		chRStatus:  chRStatus,
		unregister: unregister,
		conn:       conn,
	}
}

func (w *SpecializedRemote) sendLoop() {
	defer func() { close(w.sendQuit) }()
	// encoded name to be sent in FnMsg.Func, so that the frontend
	// knows which SpecializedRemote to assign the task.
	nameMsg := msgp.AppendString(nil, w.name)
	for t := range w.chInput {
		w.predispatch(t)

		w.approvalq <- FnMsg{Tid: t.id, Res: resToMsg(t.res), Func: nameMsg}
	}
}

func (w *SpecializedRemote) recvLoop() {
	defer func() { close(w.recvQuit) }()
	for r := range w.chRStatus {
		w.postreceive(r)
	}
}

func (w *SpecializedRemote) batchCancel(pred taskPredicateFn) {
	var tids []uint
	w.pending.mu.Lock()
	for tid := range w.pending.m {
		if !pred(tid) {
			tids = append(tids, tid)
		}
	}
	w.pending.mu.Unlock()
	for _, tid := range tids {
		w.postreceive(ResultMsg{Tid: tid, Exception: "UserCancelled"})
	}
	// No need to send back anything since the source quits after initiating batchCancel
}

func (w *SpecializedRemote) close() {
	// assume that w.chInput will not be passed in data during and after
	// this function call
	w.setClosing()
	// for backendless sworker, w.conn is already closed and the following errs silently
	bye, _ := (&ControlMsg{Cmd: "FIN"}).MarshalMsg(nil)
	w.mu.Lock()
	_, _ = w.conn.Write(bye)
	w.mu.Unlock()

	w.closeSend()

	// wait for w.rstatusq's sender to close
	w.unregister()
	<-w.recvQuit

	w.mu.Lock()
	_ = w.conn.Close()
	w.mu.Unlock()

	// migrate all pending tasks once the pending gets stable
	w.ejectPending()
}
