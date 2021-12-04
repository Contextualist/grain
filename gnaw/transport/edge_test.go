package transport

import (
	"bufio"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func assertEq(t *testing.T, a interface{}, b interface{}) {
	if a != b {
		t.Fatalf("%s != %s", a, b)
	}
}

func check(t *testing.T, err error) {
	if err != nil {
		t.Fatalf("%v", err)
	}
}

func TestPing(t *testing.T) {
	l := func(s chan struct{}) {
		l, err := Listen("edge:///tmp/edge-test")
		check(t, err)
		s <- struct{}{}
		conn, err := l.Accept()
		check(t, err)

		fmt.Fprintf(conn, "pong\n")
		r, err := bufio.NewReader(conn).ReadString('\n')
		check(t, err)
		assertEq(t, r, "ping\n")

		err = conn.Close()
		check(t, err)
		err = l.Close()
		check(t, err)
		s <- struct{}{}
	}
	d := func(s chan struct{}) {
		go func() { // Dial blocks, so just wait for a while
			time.Sleep(5 * time.Millisecond)
			s <- struct{}{}
		}()
		conn, err := Dial("edge:///tmp/edge-test")
		check(t, err)

		fmt.Fprintf(conn, "ping\n")
		r, err := bufio.NewReader(conn).ReadString('\n')
		check(t, err)
		assertEq(t, r, "pong\n")

		err = conn.Close()
		check(t, err)
		s <- struct{}{}
	}
	cl, cd := make(chan struct{}), make(chan struct{})

	go l(cl)
	<-cl
	go d(cd)
	<-cd
	<-cl
	<-cd

	go d(cd)
	<-cd
	go l(cl)
	<-cl
	<-cl
	<-cd
}

func TestMain(m *testing.M) {
	zerolog.SetGlobalLevel(zerolog.DebugLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.Stamp})
	os.Exit(m.Run())
}
