package transport

import (
	"context"
	"fmt"
	"net"
)

var listenConfig = net.ListenConfig{
	Control: control,
}

func listen(network, address string) (net.Listener, error) {
	return listenConfig.Listen(context.Background(), network, address)
}

func listenPacket(network, address string) (net.PacketConn, error) {
	return listenConfig.ListenPacket(context.Background(), network, address)
}

func dial(network, laddr, raddr string) (net.Conn, error) {
	nla, err := resolveAddr(network, laddr)
	if err != nil {
		return nil, fmt.Errorf("Dial failed to resolve laddr %v: %w", laddr, err)
	}
	d := net.Dialer{
		Control:   control,
		LocalAddr: nla,
	}
	return d.Dial(network, raddr)
}

func resolveAddr(network, address string) (net.Addr, error) {
	switch network {
	default:
		return nil, net.UnknownNetworkError(network)
	case "ip", "ip4", "ip6":
		return net.ResolveIPAddr(network, address)
	case "tcp", "tcp4", "tcp6":
		return net.ResolveTCPAddr(network, address)
	case "udp", "udp4", "udp6":
		return net.ResolveUDPAddr(network, address)
	case "unix", "unixgram", "unixpacket":
		return net.ResolveUnixAddr(network, address)
	}
}
