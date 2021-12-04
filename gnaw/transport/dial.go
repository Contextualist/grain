// General dial and listen for net
package transport

import (
	"errors"
	"fmt"
	"net"
	"net/url"
)

type dopts struct {
	Key   string
	Iface string
}

// General dial for all protocols
func Dial(rawurl string) (net.Conn, error) {
	proto, addr, opts, err := parseURL(rawurl)
	if err != nil {
		return nil, fmt.Errorf("Bad URL: %w", err)
	}
	switch proto {
	case "tcp", "unix":
		return net.Dial(proto, addr)
	case "edge":
		return DialE(addr)
	case "bridge":
		return DialB(addr, opts.Key, opts.Iface)
	}
	return nil, errors.New("No protocol matched")
}

// General listener for all protocols
func Listen(rawurl string) (net.Listener, error) {
	proto, addr, opts, err := parseURL(rawurl)
	if err != nil {
		return nil, fmt.Errorf("Bad URL: %w", err)
	}
	switch proto {
	case "tcp", "unix":
		return net.Listen(proto, addr)
	case "edge":
		return ListenE(addr)
	case "bridge":
		return ListenB(addr, opts.Key, opts.Iface)
	}
	return nil, fmt.Errorf("Unknown protocol: %s", proto)
}

func parseURL(rawurl string) (proto, addr string, opts *dopts, err error) {
	u, err := url.Parse(rawurl)
	if err != nil {
		return
	}
	proto, addr = u.Scheme, u.Host
	switch proto {
	case "tcp":
		return
	case "bridge":
		opts = new(dopts)
		opts.Key = u.User.Username()
		if opts.Key == "" {
			return "", "", nil, errors.New("A session key must be specified for the bridge protocol")
		}
		q, err := url.ParseQuery(u.RawQuery)
		if err != nil {
			return "", "", nil, err
		}
		if iq, ok := q["iface"]; ok {
			opts.Iface = iq[0]
		}
	case "edge", "unix":
		addr = u.Path
	default:
		return "", "", nil, fmt.Errorf("Unknown protocol %s", proto)
	}
	return
}
