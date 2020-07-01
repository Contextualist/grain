package main

import (
	"flag"
	"log"
	"net"
	"strconv"
	"strings"
)

var (
	port    = flag.Int("p", 9555, "port for the bridge server")
	loadBal = flag.Int("n", 1, "number of coexisting heads with the same key allowed (for load balancing)")
)

func headLoop(s net.Conn, key string) {
	log.Printf("head %s is ready\n", key)
	chCancel := make(chan struct{})
	go func() {
		buf := make([]byte, 1)
		s.Read(buf)
		close(chCancel)
	}()

	chBacklog := backlogs.Get(key).(chan struct{})
	chRelay := relays.Get(key).(chan struct{})
	var token struct{}
	select {
	case token = <-chBacklog: // backlog acts as a capacity limiter, init with N tokens. N=1: exclusive relay; N=inf: max load balance
	default:
		token = <-chRelay // if we reach the capacity limit, acquire from a running instance
	}

	chNew := subd2head.Get(key).(chan []byte)
	for {
		select {
		case subd := <-chNew:
			_ = sendPacket(s, subd)
			log.Printf("informed head %s of new subd %s\n", key, subd)
		case <-chCancel:
			chBacklog <- token // recycle the token
			log.Printf("head %s quits\n", key)
			return
		case chRelay <- token: // a new instance request a token
			log.Printf("previous head %s hands control over to a new instance\n", key)
			<-chCancel
			log.Printf("previous head %s quits\n", key)
			return
		}
	}
}

func handle(s net.Conn) {
	defer s.Close()
	xPubl := s.RemoteAddr().String()
	pkt, err := recvPacket(s)
	if !ok_(err) {
		return
	}
	_f := strings.Split(string(pkt), ",")
	CMD, key, payload := _f[0], _f[1], _f[2]
	switch CMD {
	case "INIT": // head subscribes to subds from session `key`
		headLoop(s, key)
	case "SUBD": // subd requests connection to head in session `key`
		subdPubl, subdPriv := xPubl, payload
		log.Printf("subd %s requests connection with head %s\n", subdPubl, key)
		subd2head.Get(key).(chan []byte) <- []byte(subdPubl + "|" + subdPriv)
		// NOTE: after this point, subd might close connection. Head shall make appropriate judgement
		err = sendPacket(s, <-head2subd.Get(subdPubl).(chan []byte))
		if !ok_(err) {
			log.Printf("broken connection from %s\n", subdPubl)
		} else {
			log.Printf("subd %s was assigned to an endpoint from head %s\n", subdPubl, key)
		}
		head2subd.Delete(subdPubl)
	case "HEAD": // head replies subd `subdPubl` with an available endpoint
		subdPubl, headPubl, headPriv := key, xPubl, payload
		head2subd.Get(subdPubl).(chan []byte) <- []byte(headPubl + "|" + headPriv)
	default:
		log.Printf("unrecognized command %s from %s (%s,%s)\n", CMD, xPubl, key, payload)
	}
}

func bridge(port int) {
	l, err := net.Listen("tcp", ":"+strconv.Itoa(port))
	if !ok_(err) {
		return
	}
	defer l.Close()
	for {
		conn, err := l.Accept()
		if !ok_(err) {
			return
		}
		go handle(conn)
	}
}

func main() {
	flag.Parse()
	bridge(*port)
}

func ok_(err error) bool {
	if err == nil {
		return true
	}
	log.Println("[ERROR]", err)
	return false
}
