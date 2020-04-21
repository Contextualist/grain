package main

import (
	"flag"
	"log"
	"net"
	"strconv"
	"strings"
)

var (
	port = flag.Int("p", 9555, "port for the bridge server")
)

func headLoop(s net.Conn, key string) {
	log.Printf("head %s is ready\n", key)
	chCancel := make(chan struct{})
	go func() {
		buf := make([]byte, 1)
		s.Read(buf)
		close(chCancel)
	}()

	chRelay := relays.Get(key)
	notify(chRelay) // take control over from previous head if there is one

	chNew := subd2head.Get(key)
	for {
		select {
		case subd := <-chNew:
			_ = sendPacket(s, subd)
			log.Printf("informed head %s of new subd %s\n", key, subd)
		case <-chCancel:
			log.Printf("head %s quits\n", key)
			return
		case <-chRelay:
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
		// all subd requests are directed to the last head subscribes in
		headLoop(s, key)
	case "SUBD": // subd requests connection to head in session `key`
		subdPubl, subdPriv := xPubl, payload
		log.Printf("subd %s requests connection with head %s\n", subdPubl, key)
		subd2head.Get(key) <- []byte(subdPubl + "|" + subdPriv)
		// NOTE: after this point, subd might close connection. Head shall make appropriate judgement
		err = sendPacket(s, <-head2subd.Get(subdPubl))
		if !ok_(err) {
			log.Printf("broken connection from %s\n", subdPubl)
		} else {
			log.Printf("subd %s was assigned to an endpoint from head %s\n", subdPubl, key)
		}
		head2subd.Delete(subdPubl)
	case "HEAD": // head replies subd `subdPubl` with an available endpoint
		subdPubl, headPubl, headPriv := key, xPubl, payload
		head2subd.Get(subdPubl) <- []byte(headPubl + "|" + headPriv)
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

func notify(ch chan []byte) {
	select {
	case ch <- nil:
	default:
	}
}
