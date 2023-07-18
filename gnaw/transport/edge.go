// Edge protocol: connection discovery depending on network filesystem only
package transport

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"math/rand"
	"net"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/gofrs/flock"
	"github.com/rs/zerolog/log"
)

type (
	infoListener struct {
		Host string            `json:"host"`
		LID  int               `json:"lid"`
		URLs map[string]string `json:"urls"`
	}
	infoDialer struct {
		Host string            `json:"host"`
		URLs map[string]string `json:"urls"`
	}
	infoEdgeFile struct {
		Listener *infoListener `json:"listener,omitempty"`
		Dialer   []infoDialer  `json:"dialer,omitempty"`
	}
)

func DialE(edgeFile string) (conn net.Conn, err error) {
	edgeLock := newFileLock(edgeFile)
	edgeLock.Lock()
	defer edgeLock.Unlock()

	host, err := os.Hostname()
	if err != nil {
		return nil, fmt.Errorf("failed to get hostname: %w", err)
	}
	info := infoEdgeFile{}
	if infoRaw, err := os.ReadFile(edgeFile); err == nil {
		if err = json.Unmarshal(infoRaw, &info); err == nil && info.Listener != nil {
			linfo := info.Listener
			chConn := make(chan net.Conn, 1)
			log.Debug().Str("host", linfo.Host).Msg("Try connecting to the listener")
			urls := linfo.URLs
			if uds, ok := urls["UDS"]; ok && linfo.Host == host { // use Unix domain socket if local
				urls = map[string]string{"UDS": uds}
			}
			tryDial(urls, linfo.Host, chConn)
			select {
			case conn = <-chConn:
				return conn, nil
			default:
			}
		}
	}

	// fall back: listen & enqueue self
	listeners, urls, err := listenAllIface()
	if err != nil {
		return nil, fmt.Errorf("failed to listen on all interface: %w", err)
	}
	info.Dialer = append(info.Dialer, infoDialer{Host: host, URLs: urls})
	infoRaw, _ := json.Marshal(info)
	err = ioutil.WriteFile(edgeFile, infoRaw, 0600)
	if err != nil {
		return nil, fmt.Errorf("cannot write to the Edge file: %w", err)
	}
	edgeLock.Unlock() // don't occupy the lock while listening; and it's OK to call it twice

	firstIn := make(chan net.Conn)
	allErr := make(chan struct{})
	var errWg sync.WaitGroup
	errWg.Add(len(listeners))
	for _, l := range listeners {
		go func(l net.Listener) {
			c, err := l.Accept()
			if err != nil {
				errWg.Done()
			}
			firstIn <- c
		}(l)
	}
	go func() { // if every listener fails, stop waiting
		errWg.Wait()
		allErr <- struct{}{}
	}()
	select {
	case conn = <-firstIn:
	case <-allErr:
		err = fmt.Errorf("all listeners for edge dialer %s failed", edgeFile)
	}
	for _, l := range listeners {
		_ = l.Close()
	}
	return
}

type EdgeListener struct { // this implements net.Listener
	edgeFile    string
	listeners   []net.Listener
	lid         int
	udsFile     string
	acceptQueue chan net.Conn
	errQueue    chan error
	closed      chan struct{}
}

func ListenE(edgeFile string) (net.Listener, error) {
	edgeLock := newFileLock(edgeFile)
	edgeLock.Lock()
	defer edgeLock.Unlock()

	el := &EdgeListener{
		edgeFile:    edgeFile,
		acceptQueue: make(chan net.Conn),
		errQueue:    make(chan error),
		closed:      make(chan struct{}),
	}

	if infoRaw, err := os.ReadFile(edgeFile); err == nil {
		info := infoEdgeFile{}
		if err = json.Unmarshal(infoRaw, &info); err == nil {
			if info.Listener != nil {
				log.Warn().Str("previous-host", info.Listener.Host).Msg("Using an edge file claimed by another listener, which might be running or didn't exit cleanly.")
			}
			for _, dinfo := range info.Dialer { // try connecting to all pending dialers
				log.Debug().Str("host", dinfo.Host).Msg("Try connecting to pending dialer")
				go tryDial(dinfo.URLs, dinfo.Host, el.acceptQueue)
			}
		}
	}

	listeners, urls, err := listenAllIface()
	if err != nil {
		return nil, fmt.Errorf("failed to listen on all interface: %w", err)
	}
	el.udsFile = tmpFilename()
	if ul, err := net.Listen("unix", el.udsFile); err == nil {
		listeners = append(listeners, ul)
		urls["UDS"] = "unix://" + el.udsFile
	}
	el.listeners = listeners
	host, err := os.Hostname()
	if err != nil {
		return nil, fmt.Errorf("failed to get hostname: %w", err)
	}
	el.lid = rand.Int()
	infoRaw, _ := json.Marshal(infoEdgeFile{
		Listener: &infoListener{
			Host: host,
			LID:  el.lid,
			URLs: urls,
		},
	})
	err = ioutil.WriteFile(edgeFile, infoRaw, 0600)
	if err != nil {
		return nil, fmt.Errorf("cannot write to the Edge file: %w", err)
	}

	for _, l := range el.listeners {
		go func(l net.Listener) {
			for {
				conn, err := l.Accept()
				if err != nil {
					el.errQueue <- err
					return
				}
				el.acceptQueue <- conn
			}
		}(l)
	}
	return el, nil
}

func (el *EdgeListener) Accept() (conn net.Conn, err error) {
	select {
	case conn = <-el.acceptQueue:
	case err = <-el.errQueue:
	case <-el.closed:
		err = errors.New("EdgeListener.Accept: use of closed network connection")
	}
	return
}

// Close all underlying listeners and optionally remove the edge file.
// This has to be called at exit for edge file clean up
func (el *EdgeListener) Close() error {
	for _, l := range el.listeners {
		_ = l.Close()
	}
DRAIN:
	for {
		select {
		case conn := <-el.acceptQueue:
			_ = conn.Close()
		case <-el.errQueue:
		default:
			break DRAIN
		}
	}
	close(el.closed)

	edgeLock := newFileLock(el.edgeFile)
	edgeLock.Lock()
	defer edgeLock.Unlock()
	if infoRaw, err := os.ReadFile(el.edgeFile); err == nil {
		info := infoEdgeFile{}
		if err = json.Unmarshal(infoRaw, &info); err == nil {
			if info.Listener.LID == el.lid {
				_ = os.Remove(el.edgeFile)
			}
		}
	}
	_ = os.Remove(el.udsFile)
	return nil
}

func (el *EdgeListener) Addr() net.Addr {
	return &EdgeAddr{el.edgeFile}
}

type EdgeAddr struct {
	edgeFile string
}

func (a *EdgeAddr) Network() string { return "edge" }
func (a *EdgeAddr) String() string  { return a.edgeFile }

// Try dialing to a list of URLs, return the first success
func tryDial(urls map[string]string, host string, chConn chan<- net.Conn) {
	for ifn, url := range urls {
		log.Debug().Str("ifn", ifn).Str("url", url).Msg("Trying")
		conn, err := Dial(url)
		if err != nil {
			log.Debug().Err(err).Msg("Failed to dial")
			continue
		}
		chConn <- conn
		return
	}
	log.Warn().Str("host", host).Msg("Failed to establish a connection")
}

func listenAllIface() (listeners []net.Listener, urls map[string]string, err error) {
	urls = make(map[string]string)
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, nil, err
	}
	for _, ic := range ifaces {
		// interface down or loopback interface
		if ic.Flags&net.FlagUp == 0 || ic.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := ic.Addrs()
		if err != nil {
			return nil, nil, err
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
				continue // not an ipv4 address; TODO: IPv6
			}
			l, err := net.Listen("tcp4", ip.String()+":0")
			if err != nil {
				log.Debug().Str("iface", ic.Name).Msg("Failed to listen")
				continue
			}
			listeners = append(listeners, l)
			urls[ic.Name] = "tcp://" + l.Addr().String()
		}
	}
	if len(listeners) == 0 {
		return nil, nil, errors.New("failed to listen on all interfaces")
	}
	return
}

func newFileLock(filename string) *flock.Flock {
	lockFile := strings.TrimSuffix(filename, filepath.Ext(filename)) + ".lock"
	return flock.New(lockFile)
}

func tmpFilename() string {
	for {
		name := path.Join(os.TempDir(), "edge-"+strconv.Itoa(int(rand.Uint32())))
		if _, err := os.Stat(name); err == nil {
			continue
		}
		return name
	}
}
