package core

import (
	"context"
	"fmt"
	"net"
	"path/filepath"
	"strconv"
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

	taskPredicateFn func(uint) bool // predicate func for filtering task

	// A Remote sends functions to its worker and watch for their results
	Remote struct {
		*RemoteBase

		mu       sync.Mutex
		conn     net.Conn
		receiver *msgp.Reader
	}
)

func newRemote(name string, res Resource, mgr *GrainManager, retryq chan<- Task, resultq chan<- ResultMsg, conn net.Conn, rcv *msgp.Reader) *Remote {
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
			if !w.closing {
				log.Error().Str("wname", w.name).Err(err).Msg("Remote.recvLoop: read error")
				w.health_dec(FULL_HEALTH)
			}
			return
		}
		atomic.StoreUint64(&trafficFlag, 1)
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
	w.closing = true
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
		IRemote
		Resource
	}
	mgrCMD    int
	mgrAction struct {
		wn  string
		w   IRemote
		cmd mgrCMD
	}
	// GrainManager manages workers and their resources.
	GrainManager struct {
		chReq     chan Task
		chAlloc   chan struct{}
		chDealloc chan rmtRes
		chCmd     chan mgrAction
		chCmdAux  chan interface{} // misc obj to be pass in / out along with the cmd
	}
)

const (
	CMD_REG mgrCMD = iota
	CMD_UNR
	CMD_TRM
	CMD_STA
	CMD_CAN
)

func newGrainManager() *GrainManager {
	return &GrainManager{
		chReq:     make(chan Task),
		chAlloc:   make(chan struct{}),
		chDealloc: make(chan rmtRes, 256),
		chCmd:     make(chan mgrAction),
		chCmdAux:  make(chan interface{}),
	}
}

// This state machine holds workers and resources internally, and respond to cmd passed in through chans.
func (mgr *GrainManager) run() {
	var pool []IRemote
	var request *Task // current pending task
	tryAlloc := func(w IRemote, t *Task) bool {
		if w.isClosing() {
			return false
		}
		if r, ok := w.getRes().Alloc(t.res); ok {
			t.res = r
			select {
			case w.getInput() <- *t: // input buffer available, fast path
				mgr.chAlloc <- struct{}{}
			default: // block alloc but don't block the manager loop
				go func(t_ Task) {
					w.getInput() <- t_
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
			wr.IRemote.getRes().Dealloc(wr.Resource)
			if request != nil && tryAlloc(wr.IRemote, request) {
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
					if matched, _ := filepath.Match(a.wn, w.getName()); !matched {
						continue
					}
					w.setClosing() // set before w.close() in case w.close() runs in next manager cycle
					if a.cmd == CMD_UNR {
						go w.close() // might need extra manager cycle; safe to move on
						pool = append(pool[:i], pool[i+1:]...)
						i--
					} else {
						w.closeSend()
						// after closeSend, len(w.pending.m) would be non-increasing
						pd := w.getPending()
						pd.mu.Lock()
						l := len(pd.m)
						pd.mu.Unlock()
						if l == 0 {
							go w.close()
							pool = append(pool[:i], pool[i+1:]...)
							i--
						} else {
							go func(a mgrAction, w IRemote) {
								w.getPending().WaitEmpty()
								a.wn = w.getName()
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
				mgr.chCmdAux <- s
			case CMD_CAN:
				pred := (<-mgr.chCmdAux).(taskPredicateFn)
				if request != nil && !pred(request.id) {
					request = nil
					mgr.chAlloc <- struct{}{}
				}
				for _, w := range pool {
					go w.batchCancel(pred)
				}
			}
		}
	}
}

func (mgr *GrainManager) runAPI(ctx context.Context, url string, strawmanSwarm int, ge *GrainExecutor) {
	ln, err := gnet.Listen(url)
	if err != nil {
		panic(err)
	}
	var sm *Strawman
	var smQuit context.CancelFunc
	if strawmanSwarm > 0 {
		sm, smQuit = newStrawman(ctx, strawmanSwarm)
	}
	go func() {
		<-ctx.Done()
		ln.Close()
	}()
	for {
		conn, err := ln.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
			}
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
			mgr.register(newRemote(*msg.Name, res, mgr, ge.prjobq, ge.Resultq, conn, rcv))
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
		case "SCL":
			currSwarmSize, err := strconv.Atoi(*msg.Name)
			if err != nil {
				break
			}
			if currSwarmSize == 0 {
				if sm != nil {
					smQuit()
					sm = nil
					log.Info().Msg("Strawman: disabled")
				}
				break
			}
			if sm == nil {
				log.Info().Int("swarm_size", currSwarmSize).Msg("Strawman: enabled")
				sm, smQuit = newStrawman(ctx, currSwarmSize)
			} else {
				log.Info().Int("swarm_size", currSwarmSize).Msg("Strawman: adjust worker scaling")
				sm.chScaleChange <- currSwarmSize
			}
		default:
			log.Warn().Str("cmd", msg.Cmd).Stringer("raddr", conn.RemoteAddr()).Msg("GrainManager received unknown command")
		}
		conn.Close()
	}
}

func (mgr *GrainManager) register(w IRemote) {
	go w.sendLoop()
	go w.recvLoop()
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

func (mgr *GrainManager) dealloc(w IRemote, res Resource) {
	mgr.chDealloc <- rmtRes{w, res}
}

func (mgr *GrainManager) stat(conn net.Conn, npending int) {
	mgr.chCmd <- mgrAction{cmd: CMD_STA}
	s := (<-mgr.chCmdAux).(*strings.Builder)
	fmt.Fprintf(s, "queued jobs: %d", npending)

	var b []byte
	b = msgp.AppendBytes(b, []byte(s.String()))
	var raw msgp.Raw
	_, _ = raw.UnmarshalMsg(b)
	rmsg, _ := (&ResultMsg{Result: raw}).MarshalMsg(nil)
	conn.Write(rmsg)
}

func (mgr *GrainManager) batchCancel(pred taskPredicateFn) {
	mgr.chCmd <- mgrAction{cmd: CMD_CAN}
	mgr.chCmdAux <- pred
}

type GrainExecutor struct {
	jobq    chan Task
	prjobq  chan Task
	Resultq chan ResultMsg
	mgr     *GrainManager
}

func NewGrainExecutor(ctx context.Context, url string, strawmanSwarm int) *GrainExecutor {
	mgr := newGrainManager()
	go mgr.run()
	ge := &GrainExecutor{
		jobq:    make(chan Task, 3000),
		prjobq:  make(chan Task, 3000),
		Resultq: make(chan ResultMsg, 3000),
		mgr:     mgr,
	}
	go mgr.runAPI(ctx, url, strawmanSwarm, ge)
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

// Filter all queued and running tasks base on a tid criterion
func (ge *GrainExecutor) Filter(pred taskPredicateFn) {
	var wg sync.WaitGroup
	filter := func(ch chan Task) {
		var newBuf []Task
	CHAN_LOOP:
		for {
			select {
			case t := <-ch:
				if pred(t.id) {
					newBuf = append(newBuf, t)
				}
			default:
				break CHAN_LOOP
			}
		}
		for _, t := range newBuf {
			ch <- t
		}
		wg.Done()
	}
	wg.Add(2)
	go filter(ge.prjobq)
	go filter(ge.jobq)
	wg.Wait()
	// drain running tasks after draining the pending ones to avoid
	// thundering herd dispatch due to a sudden availability of resources
	ge.mgr.batchCancel(pred)
}

func (ge *GrainExecutor) Close() {
	ge.mgr.unregister("*")
}
