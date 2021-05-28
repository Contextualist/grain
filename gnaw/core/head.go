package core

import (
	"errors"
	"fmt"
	"io"
	"net"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	gnet "github.com/Contextualist/grain/gnaw/transport"
	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

const (
	FULL_HEALTH         = 3
	HEARTBEAT_INTERVAL  = 10 * time.Second
	HEARTBEAT_TOLERANCE = 3
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

	// A Remote sends functions to its worker and watch for their results
	Remote struct {
		name    string
		res     Resource
		closing bool
		health  int64 // need to be manipulated with atomic ops

		retryq  chan<- Task
		resultq chan<- ResultMsg
		mgr     *GrainManager
		pending *pendingTaskMap

		chInput       chan Task
		closeSendOnce sync.Once
		sendQuit      chan struct{}
		recvQuit      chan struct{}
		mu            sync.Mutex
		conn          net.Conn
	}
)

func newRemote(name string, res Resource, mgr *GrainManager, retryq chan<- Task, resultq chan<- ResultMsg, conn net.Conn) *Remote {
	return &Remote{
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
		conn:     conn,
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
		var timeout *time.Timer
		if wt, ok := t.res.(*multiResource).resm["WTime"]; ok { // NOTE: assumed multiResource
			tid := t.id
			timeout = time.AfterFunc(wt.(*wtime).t+3*time.Minute, func() {
				atomic.AddUint64(&DefaultStat.lostOrLateResponse, 1)
				log.Debug().Uint("tid", tid).Msg("resubmit due to 3 min pass timeout")
				w.resubmit(tid)
			})
		}
		w.pending.Store(t.id, pendingTask{t.res, t.rawFn, timeout})

		w.mu.Lock()
		err := (&FnMsg{t.id, resToMsg(t.res), t.rawFn}).EncodeMsg(sender)
		if err != nil {
			w.mgr.health_dec(w, FULL_HEALTH)
			w.mu.Unlock()
			return
		}
		err = sender.Flush()
		if err != nil {
			w.mgr.health_dec(w, FULL_HEALTH)
			w.mu.Unlock()
			return
		}
		w.mu.Unlock()
	}
}

// pass on the result or request a retry; notify resource management
func (w *Remote) recvLoop(receiver *msgp.Reader) {
	defer func() { close(w.recvQuit) }()
	var trafficFlag uint64
	go func() {
		t := time.NewTicker(HEARTBEAT_INTERVAL * HEARTBEAT_TOLERANCE)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				if atomic.CompareAndSwapUint64(&trafficFlag, 1, 0) {
					continue
				}
				log.Warn().Str("wname", w.name).Msg("Remote.recvLoop: heartbeat response timeout")
				w.mgr.health_dec(w, FULL_HEALTH)
				return
			case <-w.recvQuit:
				return
			}
		}
	}()
	for {
		var r ResultMsg
		err := r.DecodeMsg(receiver)
		if err != nil {
			if !(errors.Is(err, net.ErrClosed) || errors.Is(err, io.ErrClosedPipe)) {
				log.Error().Str("wname", w.name).Err(err).Msg("Remote.recvLoop: read error")
				w.mgr.health_dec(w, FULL_HEALTH)
			}
			return
		}
		atomic.StoreUint64(&trafficFlag, 1)
		if r.Tid == 0 { // assume to be heartbeat response
			continue
		}

		if r.Ok {
			pt, ok := w.pending.LoadAndDelete(r.Tid)
			if !ok {
				atomic.AddUint64(&DefaultStat.lateResponse, 1)
				log.Info().Str("wname", w.name).Uint("tid", r.Tid).Msg("Remote.recvLoop: received phantom job's result")
				continue
			}
			atomic.AddUint64(&DefaultStat.completed, 1)
			atomic.StoreInt64(&w.health, FULL_HEALTH)
			w.resultq <- r
			w.mgr.dealloc(w, pt.res)
		} else {
			atomic.AddUint64(&DefaultStat.exception, 1)
			log.Debug().Uint("tid", r.Tid).Msg("resubmit due to exception")
			w.resubmit(r.Tid)
		}
	}
}

func (w *Remote) resubmit(tid uint) {
	pt, ok := w.pending.LoadAndDelete(tid)
	if !ok {
		return // This job should have been taken care
	}
	w.mgr.health_dec(w, 1)
	w.retryq <- Task{tid, pt.res, pt.rawFn}
	w.mgr.dealloc(w, pt.res)
}

func (w *Remote) closeSend() {
	w.closeSendOnce.Do(func() {
		close(w.chInput)
		<-w.sendQuit
	})
}

func (w *Remote) close() {
	// assume that w.chInput will not be passed in data during and after
	// this function call
	bye, _ := (&ControlMsg{Cmd: "FIN"}).MarshalMsg(nil)
	w.mu.Lock()
	_, _ = w.conn.Write(bye)
	_ = w.conn.Close()
	w.mu.Unlock()

	// migrate all pending tasks once the pending gets stable
	w.closeSend()
	<-w.recvQuit
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

type (
	rmtRes struct {
		*Remote
		Resource
	}
	mgrCMD    int
	mgrAction struct {
		wn  string
		w   *Remote
		cmd mgrCMD
	}
	// GrainManager manages workers and their resources.
	GrainManager struct {
		chReq     chan Task
		chAlloc   chan struct{}
		chDealloc chan rmtRes
		chCmd     chan mgrAction
		chStat    chan *strings.Builder
	}
)

const (
	CMD_REG mgrCMD = iota
	CMD_UNR
	CMD_TRM
	CMD_STA
)

func newGrainManager() *GrainManager {
	return &GrainManager{
		chReq:     make(chan Task),
		chAlloc:   make(chan struct{}),
		chDealloc: make(chan rmtRes, 256),
		chCmd:     make(chan mgrAction),
		chStat:    make(chan *strings.Builder),
	}
}

// This state machine holds workers and resources internally, and respond to cmd passed in through chans.
func (mgr *GrainManager) run() {
	var pool []*Remote
	var request *Task // current pending task
	tryAlloc := func(w *Remote, t *Task) bool {
		if w.closing {
			return false
		}
		if r, ok := w.res.Alloc(t.res); ok {
			t.res = r
			select {
			case w.chInput <- *t: // input buffer available, fast path
				mgr.chAlloc <- struct{}{}
			default: // block alloc but don't block the manager loop
				go func(t_ Task) {
					w.chInput <- t_
					mgr.chAlloc <- struct{}{}
				}(*t)
			}
			return true
		}
		return false
	}
LOOP:
	for {
		select {
		case t := <-mgr.chReq:
			for _, w := range pool { // check if any avail
				if tryAlloc(w, &t) {
					continue LOOP
				}
			}
			request = &t // wait for resource
		case wr := <-mgr.chDealloc: // new resource
			wr.Remote.res.Dealloc(wr.Resource)
			if request != nil && tryAlloc(wr.Remote, request) {
				request = nil
			}
		case a := <-mgr.chCmd:
			switch a.cmd {
			case CMD_REG: // new worker joins with resource
				if request != nil && tryAlloc(a.w, request) {
					request = nil
				}
				pool = append(pool, a.w)
			case CMD_UNR, CMD_TRM: // quit worker(s)
				for i := 0; i < len(pool); i++ {
					w := pool[i]
					if matched, _ := filepath.Match(a.wn, w.name); !matched {
						continue
					}
					w.closing = true
					if a.cmd == CMD_UNR {
						go w.close() // might need extra manager cycle; safe to move on
						pool = append(pool[:i], pool[i+1:]...)
						i--
					} else {
						w.closeSend()
						// after closeSend, len(w.pending.m) would be non-increasing
						w.pending.mu.Lock()
						l := len(w.pending.m)
						w.pending.mu.Unlock()
						if l == 0 {
							go w.close()
							pool = append(pool[:i], pool[i+1:]...)
							i--
						} else {
							go func(a mgrAction, w *Remote) {
								w.pending.WaitEmpty()
								a.wn = w.name
								mgr.chCmd <- a
							}(a, w)
						}
					}
				}
			case CMD_STA:
				s := workerStatistics(pool)
				if request != nil {
					fmt.Fprintf(s, "next pending job's res: %s\n", request.res.String())
				}
				mgr.chStat <- s
			}
		}
	}
}

func (mgr *GrainManager) runAPI(url string, ge *GrainExecutor) {
	ln, err := gnet.Listen(url)
	if err != nil {
		panic(err)
	}
	for {
		conn, err := ln.Accept()
		if err != nil {
			if nerr, ok := err.(gnet.Error); ok && nerr.Temporary() {
				log.Error().Err(err).Msg("GrainManager.runAPI: accept error")
				continue
			}
			panic(err)
		}
		rcv := msgp.NewReader(conn)
		var msg ControlMsg
		err = msg.DecodeMsg(rcv)
		if err != nil {
			log.Error().Interface("conn", conn).Err(err).Msg("Error handling the first packet")
			conn.Close()
			continue
		}
		switch msg.Cmd {
		case "CON": // register a worker and plug it into the executor
			res := ResFromMsg(msg.Res)
			log.Info().Str("wname", *msg.Name).Stringer("res", res).Msg("Worker joined")
			mgr.register(newRemote(*msg.Name, res, mgr, ge.prjobq, ge.Resultq, conn), rcv)
			continue // keep this connection
		case "REG":
			// passive worker, not implemented yet
		case "UNR":
			log.Info().Str("wname", *msg.Name).Msg("Worker is leaving now")
			mgr.unregister(*msg.Name)
		case "TRM":
			log.Info().Str("wname", *msg.Name).Msg("Worker is going to leave")
			mgr.terminate(*msg.Name)
		case "STA":
			mgr.stat(conn, len(ge.jobq)+len(ge.prjobq))
		default:
			log.Warn().Str("cmd", msg.Cmd).Stringer("raddr", conn.RemoteAddr()).Msg("GrainManager received unknown command")
		}
		conn.Close()
	}
}

func (mgr *GrainManager) register(w *Remote, receiver *msgp.Reader) {
	go w.sendLoop()
	go w.recvLoop(receiver)
	mgr.chCmd <- mgrAction{w: w, cmd: CMD_REG}
}

func (mgr *GrainManager) unregister(wn string) {
	mgr.chCmd <- mgrAction{wn: wn, cmd: CMD_UNR}
}

func (mgr *GrainManager) terminate(wn string) {
	mgr.chCmd <- mgrAction{wn: wn, cmd: CMD_TRM}
}

// Only one call of schedule is allowed at any time.
func (mgr *GrainManager) schedule(t Task) {
	mgr.chReq <- t
	<-mgr.chAlloc // block until t is sent to a remote
}

func (mgr *GrainManager) dealloc(w *Remote, res Resource) {
	mgr.chDealloc <- rmtRes{w, res}
}

func (mgr *GrainManager) health_dec(w *Remote, v int64) {
	if atomic.AddInt64(&w.health, -v) > 0 {
		return
	}
	log.Warn().Str("wname", w.name).Msg("Quit worker due to poor health")
	mgr.unregister(w.name)
}

func (mgr *GrainManager) stat(conn net.Conn, npending int) {
	mgr.chCmd <- mgrAction{cmd: CMD_STA}
	s := <-mgr.chStat
	fmt.Fprintf(s, "queued jobs: %d", npending)

	var b []byte
	b = msgp.AppendBytes(b, []byte(s.String()))
	var raw msgp.Raw
	_, _ = raw.UnmarshalMsg(b)
	rmsg, _ := (&ResultMsg{Result: raw}).MarshalMsg(nil)
	conn.Write(rmsg)
}

type GrainExecutor struct {
	jobq    chan Task
	prjobq  chan Task
	Resultq chan ResultMsg
	mgr     *GrainManager
}

func NewGrainExecutor(url string) *GrainExecutor {
	mgr := newGrainManager()
	go mgr.run()
	ge := &GrainExecutor{
		jobq:    make(chan Task, 3000),
		prjobq:  make(chan Task, 3000),
		Resultq: make(chan ResultMsg, 3000),
		mgr:     mgr,
	}
	go mgr.runAPI(url, ge)
	return ge
}

func (ge *GrainExecutor) Submit(id uint, res Resource, rawFn msgp.Raw) {
	ge.jobq <- Task{id, res, rawFn}
}

func (ge *GrainExecutor) SubmitPrioritized(id uint, res Resource, rawFn msgp.Raw) {
	ge.prjobq <- Task{id, res, rawFn}
}

func (ge *GrainExecutor) Run() {
	for {
		var t Task
		select {
		case t = <-ge.prjobq: // prioritize: retry / prioritized jobs
		default:
			select {
			case t = <-ge.prjobq:
			case t = <-ge.jobq:
			}
		}
		ge.mgr.schedule(t)
	}
}
