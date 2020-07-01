package main

import (
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestProtocol(t *testing.T) {
	*loadBal = 1
	var wg sync.WaitGroup
	wg.Add(3)
	go subd_(t, &wg, "keyX", "0")
	go subd_(t, &wg, "keyX", "1")
	go head_(t, &wg, "keyX", makeSet([]string{"0", "1"}))
	wg.Wait()
}

func TestKey(t *testing.T) {
	*loadBal = 1
	var wg sync.WaitGroup
	wg.Add(4)
	go subd_(t, &wg, "keyY", "1")
	go head_(t, &wg, "keyX", makeSet([]string{"0"}))
	go subd_(t, &wg, "keyX", "0")
	go head_(t, &wg, "keyY", makeSet([]string{"1"}))
	wg.Wait()
}

func TestRelay(t *testing.T) {
	*loadBal = 1
	var wg, wg0 sync.WaitGroup
	wg.Add(3)
	wg0.Add(1)
	go head_(t, &wg0, "keyA", makeSet([]string{"0", "placeholder"}))
	subd_(t, &wg, "keyA", "0")
	started := make(chan struct{})
	go head_(t, &wg, "keyA", makeSet([]string{"1"}), started)
	<-started
	time.Sleep(1 * time.Millisecond) // albeit we wait till INIT request is sent, bridge server still occassionally slower to accept it.
	subd_(t, &wg, "keyA", "1")
	wg.Wait()
}

func TestLoadBal(t *testing.T) {
	*loadBal = 2
	var wg, wg0 sync.WaitGroup
	wg.Add(2)
	wg0.Add(2)
	started := make(chan struct{})
	// Each subd request can go to one of the head. We don't know which.
	go head_(t, &wg0, "keyB", makeSet([]string{"0", "1"}), started)
	go head_(t, &wg0, "keyB", makeSet([]string{"0", "1"}), started)
	<-started
	<-started
	subd_(t, &wg, "keyB", "0")
	subd_(t, &wg, "keyB", "1")
	wg.Wait()
}

func head_(t *testing.T, wg *sync.WaitGroup, key string, ids set, started ...chan struct{}) {
	defer wg.Done()
	h, hb := newMemTCPConnPair()
	defer h.Close()
	go handle(hb)
	sendPacket(h, []byte("INIT,"+key+","))
	if len(started) > 0 {
		started[0] <- struct{}{}
	}

	for i := len(ids); i > 0; i-- {
		r, _ := recvPacket(h)
		t.Log("head recv subd's request", string(r))
		subdPubl, subdPriv := addrSplit(r)
		// extract id and send back, so that the subd can tell if it recv the matched message
		id := strings.TrimPrefix(subdPriv, "l:subdPriv")
		if !ids.Has(id) {
			t.Fatalf("head %s recv unknown subd id %s", key, id)
		}
		delete(ids, id)
		h2, h2b := newMemTCPConnPair() // This connection is for P2P
		go handle(h2b)
		sendPacket(h2, []byte("HEAD,"+subdPubl+",l:headPriv"+id))
		h2.Close()
	}
	if len(ids) != 0 {
		t.Fatalf("head %s missing subd id(s) %s", key, ids)
	}
}

func subd_(t *testing.T, wg *sync.WaitGroup, key, id string) {
	defer wg.Done()
	s, sb := newMemTCPConnPair()
	defer s.Close()
	go handle(sb)
	sendPacket(s, []byte("SUBD,"+key+",l:subdPriv"+id))
	r, _ := recvPacket(s)
	t.Log("subd recv head's alloc", string(r))
	_, headPriv := addrSplit(r)
	if strings.TrimPrefix(headPriv, "l:headPriv") != id {
		t.Fatalf("subd recv unmatched headPriv %s, expect one ends with %s", headPriv, id)
	}
}

type memTCPConn struct {
	*io.PipeWriter
	*io.PipeReader
	la, ra *fakeAddr
}

var _p uint32

func newMemTCPConnPair() (net.Conn, net.Conn) {
	ra, wa := io.Pipe()
	rb, wb := io.Pipe()
	p := atomic.AddUint32(&_p, 2)
	aa := fakeAddr("l:" + strconv.Itoa(int(p-1)))
	ab := fakeAddr("l:" + strconv.Itoa(int(p)))
	return &memTCPConn{wa, rb, &aa, &ab}, &memTCPConn{wb, ra, &ab, &aa}
}

func (c *memTCPConn) Close() error {
	c.PipeWriter.Close()
	c.PipeReader.Close()
	return nil
}
func (c *memTCPConn) LocalAddr() net.Addr                { return c.la }
func (c *memTCPConn) RemoteAddr() net.Addr               { return c.ra }
func (c *memTCPConn) SetDeadline(t time.Time) error      { return nil }
func (c *memTCPConn) SetReadDeadline(t time.Time) error  { return nil }
func (c *memTCPConn) SetWriteDeadline(t time.Time) error { return nil }

type fakeAddr string

func (s *fakeAddr) Network() string { return "TCP" }
func (s *fakeAddr) String() string  { return string(*s) }

func addrSplit(p []byte) (string, string) {
	_f := strings.Split(string(p), "|")
	return _f[0], _f[1]
}

type set map[string]struct{}

func makeSet(a []string) (s set) {
	s = make(set)
	for _, x := range a {
		s[x] = struct{}{}
	}
	return
}
func (s set) Has(k string) bool {
	_, ok := s[k]
	return ok
}
