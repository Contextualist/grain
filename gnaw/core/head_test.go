package core

import (
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net"
	"os"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

func testPlain(t *testing.T, N, M int, workerf func(net.Conn, chan<- struct{})) {
	t.Cleanup(DefaultStat.Log)
	ge := newTestGrainExecutor()
	chFin := make(chan struct{})
	go func() {
		defer ge.mgr.unregister("*")
		chQuit := make(chan struct{})
		for i := 0; i < M; i++ {
			addWorker(fmt.Sprintf("tp-w%d", i), And(Memory(8)), func(c net.Conn) { workerf(c, chQuit) }, ge)
		}
		i := M
		for {
			select {
			case <-chQuit:
				i++
				addWorker(fmt.Sprintf("tp-w%d", i), And(Memory(8)), func(c net.Conn) { workerf(c, chQuit) }, ge)
			case <-chFin:
				return
			}
		}
	}()
	for i := 1; i < N+1; i++ {
		ge.Submit(uint(i), And(Memory(1)), nil)
	}
	rs := make([]bool, N+1)
	for i := 0; i < N; i++ {
		r := <-ge.Resultq
		assertEq(t, rs[r.Tid], false)
		rs[r.Tid] = true
	}
	for _, received := range rs[1:] {
		assertEq(t, received, true)
	}
	chFin <- struct{}{}
}
func TestSimple(t *testing.T) {
	testPlain(t, 30, 1, func(c net.Conn, chQ chan<- struct{}) { simpleWorker(c) })
}
func TestLatency(t *testing.T) {
	testPlain(t, 30, 1, func(c net.Conn, chQ chan<- struct{}) { latencyErrorWorker(c, 100*time.Microsecond, 0.1, chQ) })
}
func TestWorkerRespawn(t *testing.T) {
	testPlain(t, 3000, 10, func(c net.Conn, chQ chan<- struct{}) { latencyErrorWorker(c, 1*time.Microsecond, 0.3, chQ) })
}

func TestManager(t *testing.T) {
	t.Parallel()
	ge := newTestGrainExecutor()
	stepWorker, waitEnter, proceed, chClosed := makeStepWorker()
	maxWait := 1500 * time.Microsecond

	// release queued job when there're new resources
	ge.Submit(1, And(Memory(1)), nil)
	go func() { waitEnter(); proceed() }()
	select {
	case <-ge.Resultq:
		t.Fatalf("get result before reg worker")
	default:
	}
	addWorker("m-w0", And(Memory(1)), stepWorker, ge)
	select {
	case <-ge.Resultq:
	case <-time.After(maxWait):
		t.Fatalf("take too long to receive result after a work reg")
	}

	// terminate waits for pending jobs to finish
	ge.Submit(2, And(Memory(1)), nil)
	waitEnter()
	ge.mgr.terminate("m-w0")
	select {
	case <-chClosed:
		t.Fatalf("terminating worker closes with pending jobs")
	default:
	}
	go proceed()
	select {
	case <-ge.Resultq:
	case <-time.After(maxWait):
		t.Fatalf("take too long to receive result from a terminating worker")
	}
	select {
	case <-chClosed:
	case <-time.After(maxWait):
		t.Fatalf("terminating worker does not close after all pending jobs done")
	}

	// unregister cancels all pending jobs
	addWorker("m-w1", And(Memory(1)), stepWorker, ge)
	ge.Submit(2, And(Memory(1)), nil)
	waitEnter()
	ge.mgr.unregister("m-w1")
	select {
	case <-chClosed:
	case <-time.After(maxWait):
		t.Fatalf("unregistered worker does not close")
	}
	go proceed()
	select {
	case <-ge.Resultq:
		t.Fatalf("receive result from a closed worker")
	case <-time.After(maxWait):
	}
	addWorker("m-w2", And(Memory(1)), stepWorker, ge)
	waitEnter()
	go proceed()
	select {
	case <-ge.Resultq:
	case <-time.After(maxWait):
		t.Fatalf("no result for the retried job")
	}
	ge.mgr.unregister("m-w2")
}

func BenchmarkExer(b *testing.B) {
	ge := newTestGrainExecutor()
	defer ge.mgr.unregister("*")
	for i := 0; i < 1; i++ {
		addWorker(fmt.Sprintf("b-w%d", i), And(Memory(8)), simpleWorker, ge)
	}
	b.ReportAllocs()
	b.ResetTimer()
	go func() {
		for i := 1; i < b.N+1; i++ {
			ge.Submit(uint(i), And(Memory(2)), nil)
		}
	}()
	for i := 0; i < b.N; i++ {
		<-ge.Resultq
	}
	b.StopTimer()
}

func addWorker(name string, res Resource, workerf func(net.Conn), ge *GrainExecutor) {
	conn := newMockEndpoint(workerf)
	rcv := msgp.NewReader(conn)
	ge.mgr.register(newRemote(name, res, ge.mgr, ge.prjobq, ge.Resultq, conn), rcv)
}

func newMockEndpoint(workerf func(net.Conn)) net.Conn {
	hc, wc := net.Pipe()
	go workerf(wc)
	return hc
}

func simpleWorker(wc net.Conn) {
	rcv, snd := msgp.NewReader(wc), msgp.NewWriter(wc)
	chTid := make(chan uint, 64)
	go func() {
		r := ResultMsg{}
		for tid := range chTid {
			r.Tid = tid
			err := r.EncodeMsg(snd)
			if returnOrElsePanic(err) {
				return
			}
			err = snd.Flush()
			if returnOrElsePanic(err) {
				return
			}
		}
	}()
	for {
		var msg FnMsg
		err := msg.DecodeMsg(rcv)
		if returnOrElsePanic(err) {
			return
		}
		chTid <- msg.Tid
	}
}

func callbackWorker(wc net.Conn, fn func(uint), fin func()) {
	rcv, snd := msgp.NewReader(wc), msgp.NewWriter(wc)
	chTid := make(chan uint, 64)
	go func() {
		r := ResultMsg{}
		for tid := range chTid {
			fn(tid)
			r.Tid = tid
			err := r.EncodeMsg(snd)
			if returnOrElsePanic(err) {
				return
			}
			err = snd.Flush()
			if returnOrElsePanic(err) {
				return
			}
		}
	}()
	for {
		var msg FnMsg
		err := msg.DecodeMsg(rcv)
		if returnOrElsePanic(err) {
			fin()
			return
		}
		if msg.Tid == 0 { // assumed as FIN msg
			continue
		}
		chTid <- msg.Tid
	}
}

func makeStepWorker() (stepWorker func(c net.Conn), waitEnter func(), proceed func(), chClosed chan struct{}) {
	chStep0, chStep1, chClosed := make(chan struct{}), make(chan struct{}), make(chan struct{})
	stepWorker = func(c net.Conn) {
		callbackWorker(c, func(_ uint) { chStep0 <- struct{}{}; <-chStep1 }, func() { chClosed <- struct{}{} })
	}
	waitEnter = func() { <-chStep0 }
	proceed = func() { chStep1 <- struct{}{} }
	return
}

func latencyErrorWorker(wc net.Conn, baseLatency time.Duration, errorRate float32, chQ chan<- struct{}) {
	rcv, snd := msgp.NewReader(wc), msgp.NewWriter(wc)
	chTid := make(chan uint)
	go func() {
		r := ResultMsg{}
		for tid := range chTid {
			r.Tid = tid
			if rand.Float32() < errorRate {
				r.Exception = "E"
			} else {
				r.Exception = ""
			}
			err := r.EncodeMsg(snd)
			if returnOrElsePanic(err) {
				return
			}
			err = snd.Flush()
			if returnOrElsePanic(err) {
				return
			}
		}
	}()
	for {
		var msg FnMsg
		err := msg.DecodeMsg(rcv)
		if returnOrElsePanic(err) {
			chQ <- struct{}{}
			return
		}
		if msg.Tid == 0 { // assumed as FIN msg
			continue
		}
		lat := time.Nanosecond * time.Duration(float64(baseLatency.Nanoseconds())*rand.ExpFloat64())
		time.AfterFunc(lat, func(tid uint) func() { return func() { chTid <- tid } }(msg.Tid))
	}
}

func returnOrElsePanic(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, io.ErrClosedPipe) || errors.Is(err, io.EOF) {
		return true
	}
	panic(err)
}

func newTestGrainExecutor() *GrainExecutor {
	mgr := newGrainManager()
	go mgr.run()
	ge := &GrainExecutor{
		jobq:    make(chan Task, 3000),
		prjobq:  make(chan Task, 3000),
		Resultq: make(chan ResultMsg, 3000),
		mgr:     mgr,
	}
	go ge.Run()
	return ge
}

func TestMain(m *testing.M) {
	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.Stamp})
	os.Exit(m.Run())
}
