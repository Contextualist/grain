// Ways to initialize conn with bridge protocol
package transport

import (
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/rs/zerolog/log"
)

const (
	CONNECT_RETRY_INTERVAL = 500 * time.Millisecond
	RENDEZVOUS_TIMEOUT     = 10 * time.Second
)

type (
	Error interface {
		error
		Temporary() bool
	}

	tempErr struct{ error }
)

func (e tempErr) Temporary() bool { return true }

func accept(l net.Listener, c_win chan<- net.Conn, cc <-chan struct{}) {
	conn, err := l.Accept()
	if err != nil {
		return
	}
	select {
	case c_win <- conn:
		log.Debug().Stringer("laddr", conn.LocalAddr()).Msg("P2P: accepted")
	case <-cc:
		conn.Close()
	}
}
func connect(laddr, raddr string, c_win chan<- net.Conn, cc <-chan struct{}) {
	var conn net.Conn
	var err error
	for {
		select {
		case <-cc:
			return
		default:
		}
		conn, err = dial("tcp", laddr, raddr)
		if err == nil {
			break
		}
		time.Sleep(CONNECT_RETRY_INTERVAL)
	}
	select {
	case c_win <- conn:
		log.Debug().Str("laddr", laddr).Str("raddr", raddr).Msg("P2P: connected")
	case <-cc:
		conn.Close()
	}
}

// Rendezvous preparation: connect to bridge and bind to a local address
func initConn(bridge, iface string) (sa net.Conn, l net.Listener, err error) {
	sa, err = dial("tcp", ":0", bridge)
	if err != nil {
		return nil, nil, fmt.Errorf("Failed to communicate with the bridge: %w", err)
	}
	var privAddr string
	if iface == "" {
		privAddr = sa.LocalAddr().String()
	} else {
		privHost, err := getPrivHost(iface)
		if err != nil {
			return nil, nil, fmt.Errorf("Unable to get iface addr: %w", err)
		}
		privAddr = privHost + ":0"
	}
	l, err = listen("tcp", privAddr) // We listen here to get a port for the iface case
	if err != nil {
		return nil, nil, fmt.Errorf("Unable to set up rendezvous: %w", err)
	}
	return
}

// Rendezvous with peer
func holePunching(peerLaddr, peerRaddr string, l net.Listener) (conn net.Conn, err error) {
	log.Debug().Msg("P2P: rendezvous")
	privAddr := l.Addr().String()
	defer l.Close()
	c_win := make(chan net.Conn)
	cc := make(chan struct{})
	defer close(cc)
	go accept(l, c_win, cc)
	go connect(privAddr, peerLaddr, c_win, cc)
	if peerRaddr != peerLaddr {
		go connect(privAddr, peerRaddr, c_win, cc)
	}
	select {
	case conn = <-c_win:
	case <-time.After(RENDEZVOUS_TIMEOUT):
		return nil, fmt.Errorf("Rendezvous timeout. Failed to established a P2P connection with %s", peerRaddr)
	}
	return conn, nil
}

// Act as a dialer/subd, requesting a connection with listener/head.
func DialB(bridge, key, iface string) (conn net.Conn, err error) {
	sa, l, err := initConn(bridge, iface)
	if err != nil {
		return nil, err
	}
	err = sendPacket(sa, []byte("SUBD,"+key+","+l.Addr().String()))
	if err != nil {
		return nil, fmt.Errorf("Failed to communicate with the bridge: %w", err)
	}
	rsp, err := receivePacket(sa)
	if err != nil {
		return nil, fmt.Errorf("Failed to communicate with the bridge: %w", err)
	}
	tmp := strings.Split(string(rsp), "|")
	peerLaddr, peerRaddr := tmp[0], tmp[1]
	return holePunching(peerLaddr, peerRaddr, l)
}

type BridgeListener struct { // this implements net.Listener
	sconn         net.Conn
	bridge, iface string
}

// Act as a listener/head, subscribing to connection requests from dialers/subds.
func ListenB(bridge, key, iface string) (net.Listener, error) {
	s, err := net.Dial("tcp", bridge)
	if err != nil {
		return nil, fmt.Errorf("Failed to communicate with the bridge: %w", err)
	}
	err = sendPacket(s, []byte("INIT,"+key+","))
	if err != nil {
		return nil, fmt.Errorf("Failed to communicate with the bridge: %w", err)
	}
	ln := &BridgeListener{
		sconn:  s,
		bridge: bridge,
		iface:  iface,
	}
	return ln, nil
}

func (bl *BridgeListener) Accept() (net.Conn, error) {
	subd, err := receivePacket(bl.sconn)
	if err != nil {
		return nil, fmt.Errorf("Connection with bridge was interruptted unexpectedly: %w", err)
	}
	tmp := strings.Split(string(subd), "|")
	peerLaddr, peerRaddr := tmp[0], tmp[1]
	sa, l, err := initConn(bl.bridge, bl.iface)
	if err != nil {
		return nil, err
	}
	err = sendPacket(sa, []byte("HEAD,"+peerRaddr+","+l.Addr().String()))
	if err != nil {
		return nil, err
	}
	conn, err := holePunching(peerLaddr, peerRaddr, l)
	if err != nil {
		return nil, tempErr{fmt.Errorf("Failed to handle subd %s: %w", peerRaddr, err)}
	}
	return conn, nil
}

func (bl *BridgeListener) Close() error {
	return bl.sconn.Close()
}

func (bl *BridgeListener) Addr() net.Addr {
	return bl.sconn.LocalAddr()
}

// Find out the gateway IP corresponding to a network interface
func getPrivHost(iface string) (string, error) {
	ifaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}
	for _, ic := range ifaces {
		// interface down or loopback interface or name not matched
		if ic.Flags&net.FlagUp == 0 || ic.Flags&net.FlagLoopback != 0 || ic.Name != iface {
			continue
		}
		addrs, err := ic.Addrs()
		if err != nil {
			return "", err
		}
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			if ip == nil || ip.IsLoopback() {
				continue
			}
			ip = ip.To4()
			if ip == nil {
				continue // not an ipv4 address
			}
			return ip.String(), nil
		}
	}
	return "", fmt.Errorf("No iface matching name %s", iface)
}
