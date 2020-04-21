package main

import (
	"encoding/binary"
	"io"
	"net"
)

type lenType uint32

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
	buf := make([]byte, plen)
	_, err = io.ReadFull(conn, buf)
	if err != nil {
		return
	}
	return buf, nil
}
