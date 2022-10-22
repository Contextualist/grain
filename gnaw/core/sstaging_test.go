package core

import (
	"context"
	"fmt"
	"net"
	"testing"
	"time"

	"github.com/tinylib/msgp/msgp"
)

func TestStager(t *testing.T) {
	t.Parallel()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stager := NewSpecializedStager()
	var MAX_DOCKS uint = 2
	go stager.Run(ctx, func(gtid uint) (uint, uint) { return gtid % MAX_DOCKS, gtid / MAX_DOCKS })
	mgr := newGrainManager()
	go mgr.run()
	maxWait := 1500 * time.Microsecond

	// registering sworker pushes event to frontend
	var dockID uint = 0
	chEvent := addMockFrontend(t, stager, dockID, MAX_DOCKS)
	chResult, chSWorkerClear := addMockSpecializedWorker(t, stager, mgr, "sw-1")
	select {
	case ev := <-chEvent:
		assertEq(t, ev.Cmd, "pushSWorker")
	case <-time.After(maxWait):
		t.Fatalf("take too long to receive sworker push")
	}

	// task life cycle
	mgr.schedule(Task{id: 1*MAX_DOCKS + dockID, res: And(Capacity(-1))})
	select {
	case r := <-chResult:
		assertEq(t, r.Tid, 1*MAX_DOCKS+dockID)
	case <-time.After(maxWait):
		t.Fatalf("take too long to get task result")
	}

	// unregistering sworker pushes event to frontend and terminates worker
	mgr.unregister("sw-1")
	select {
	case ev := <-chEvent:
		assertEq(t, ev.Cmd, "quitSWorker")
	case <-time.After(maxWait):
		t.Fatalf("take too long to receive sworker quit notification")
	}
	select {
	case <-chSWorkerClear:
	case <-time.After(maxWait):
		t.Fatalf("take too long for worker to quit")
	}
}

func mockSpecializedWorker(t *testing.T, name string, c net.Conn, notifyClear chan<- interface{}) {
	// Simply waiting for a FIN signal
	rcv := msgp.NewReader(c)
	var msg ControlMsg
	err := msg.DecodeMsg(rcv)
	if returnOrElsePanic(err) {
		return
	}
	assertEq(t, msg.Cmd, "FIN", fmt.Sprintf("sworker %s not receiving a proper FIN", name))
	close(notifyClear)
}

func addMockSpecializedWorker(t *testing.T, s *SpecializedStager, mgr *GrainManager, name string) (<-chan ResultMsg, <-chan interface{}) {
	hc, wc := net.Pipe()
	chResult := make(chan ResultMsg)
	notifyClear := make(chan interface{})
	go mockSpecializedWorker(t, name, wc, notifyClear)
	r := s.addSpecializedRemote(name, And(Capacity(1)), nil, mgr, nil, hc)
	r.resultq = chResult // retrive result for testing purpose
	mgr.register(r)
	return chResult, notifyClear
}

func mockFrontend(t *testing.T, id uint, c net.Conn, chEvent chan<- *ControlMsg) {
	snd, rcv := msgp.NewWriter(c), msgp.NewReader(c)
	var msg ControlMsg
	err := msg.DecodeMsg(rcv)
	if returnOrElsePanic(err) {
		return
	}
	assertEq(t, msg.Cmd, "hsAck", fmt.Sprintf("frontend %d not receiving a proper hsAck", id))

	defer close(chEvent)
	for {
		msg := make(map[string]interface{})
		err := rcv.ReadMapStrIntf(msg)
		if returnOrElsePanic(err) {
			return
		}
		if cmd, ok := msg["cmd"]; ok { // pushSWorker, quitSWorker
			name, _ := msg["name"].(string)
			chEvent <- &ControlMsg{Cmd: cmd.(string), Name: &name}
			continue
		}
		// send back rstatus stub
		(&ResultMsg{Tid: uint(msg["tid"].(int64)), Exception: "", Result: msgp.AppendString(nil, msg["func"].(string))}).EncodeMsg(snd)
		if returnOrElsePanic(err) {
			return
		}
		if err = snd.Flush(); returnOrElsePanic(err) {
			return
		}
	}
}

func addMockFrontend(t *testing.T, s *SpecializedStager, id uint, maxDocks uint) <-chan *ControlMsg {
	chEvent := make(chan *ControlMsg)
	fc, hc := net.Pipe()
	go mockFrontend(t, id, fc, chEvent)
	s.AddFeedbackRemote(id, hc, func(rtid uint) uint { return rtid*maxDocks + id })
	return chEvent
}
