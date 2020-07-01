package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"net"
)

type lenType uint32

const lenCap = 1e3

func sendPacket(conn net.Conn, data []byte) (err error) {
	err = binary.Write(conn, binary.BigEndian, lenType(len(data)))
	if err != nil {
		return
	}
	_, err = conn.Write(data)
	return err
}

func recvPacket(conn net.Conn) (data []byte, err error) {
	var plen lenType
	err = binary.Read(conn, binary.BigEndian, &plen)
	if err != nil {
		return
	}
	if plen > lenCap {
		return nil, fmt.Errorf("received suspicious packet header declearing a large len: %d", plen)
	}
	buf := make([]byte, plen)
	_, err = io.ReadFull(conn, buf)
	if err != nil {
		return
	}
	return buf, nil
}
