package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/Contextualist/grain/gnaw/core"
	gnet "github.com/Contextualist/grain/gnaw/transport"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

const DOCK_COOLDOWN = 3 * time.Minute

var (
	hurl     = flag.String("hurl", "", "URL for RemoteExers to connect")
	wurl     = flag.String("wurl", "", "URL for Workers to connect")
	maxdocks = flag.Uint("n", 3, "Maximum numbers of RemoteExers allowed to connect")
	verbose  = flag.Bool("verbose", false, "Print out debug level log")
	printVer = flag.Bool("version", false, "Print version and exit")

	VERSION    string // build-time injected
	MAX_DOCKS  uint
	docksAvail chan uint
)

func dockLoop(conn net.Conn, exer *core.GrainExecutor, dockID uint, chRet <-chan core.ResultMsg, dockClose func()) {
	defer func() {
		_ = conn.Close()
		dockClose()
		log.Info().Uint("dockID", dockID).Msg("RemoteExer quits")
		time.Sleep(DOCK_COOLDOWN)
		docksAvail <- dockID
		log.Info().Uint("dockID", dockID).Msg("Dock is now available")
	}()

	go func() { // send results back
		snd := msgp.NewWriter(conn)
		for r := range chRet {
			err := r.EncodeMsg(snd)
			if err != nil {
				return
			}
			err = snd.Flush()
			if err != nil {
				return
			}
		}
	}()

	rcv := msgp.NewReader(conn)
	var hsmsg core.ControlMsg
	err := hsmsg.DecodeMsg(rcv)
	if err != nil {
		log.Error().Uint("dockID", dockID).Err(err).Msg("Error handling handshake from RemoteExer")
		return
	}
	var submit func(uint, core.Resource, msgp.Raw)
	if strings.HasSuffix(*hsmsg.Name, "-p") {
		submit = exer.SubmitPrioritized
	} else {
		submit = exer.Submit
	}
	log.Info().Uint("dockID", dockID).Str("name", *hsmsg.Name).Msg("RemoteExer connected")

	for {
		var msg core.FnMsg
		err := msg.DecodeMsg(rcv)
		if err != nil {
			if !errors.Is(err, io.EOF) {
				log.Error().Uint("dockID", dockID).Err(err).Msg("Error handling the task packet from RemoteExer")
			}
			return
		}
		res := core.ResFromMsg(&msg.Res)
		submit(msg.Tid*MAX_DOCKS+dockID, res, msg.Func)
	}
}

func run() {
	exer := core.NewGrainExecutor(*wurl)
	go exer.Run()

	var mu sync.RWMutex
	chDocks := make(map[uint]chan<- core.ResultMsg)

	go func() { // relay results from exer to docks
		for r := range exer.Resultq {
			mu.RLock()
			c, ok := chDocks[r.Tid%MAX_DOCKS]
			if !ok {
				log.Info().Uint("dockID", r.Tid%MAX_DOCKS).Msg("Received result for quitted dock")
				mu.RUnlock()
				continue
			}
			r.Tid = r.Tid / MAX_DOCKS
			c <- r
			mu.RUnlock()
		}
	}()

	ln, err := gnet.Listen(*hurl)
	if err != nil {
		panic(err)
	}
	for {
		conn, err := ln.Accept()
		if err != nil {
			if nerr, ok := err.(gnet.Error); ok && nerr.Temporary() {
				log.Error().Err(err).Msg("main.run: accept error")
				continue
			}
			panic(err)
		}
		var dc uint
		select {
		case dc = <-docksAvail:
		default:
			log.Error().Uint("MAX_DOCKS", MAX_DOCKS).Msg("Number of RemoteExers reach maximum, reject a connection")
			_ = conn.Close()
			continue
		}
		chDock := make(chan core.ResultMsg)
		mu.Lock()
		chDocks[dc] = chDock
		mu.Unlock()
		dclose := func(dc uint) func() {
			return func() { // closure for dock cleanup
				mu.Lock()
				defer mu.Unlock()
				close(chDocks[dc])
				delete(chDocks, dc)
			}
		}(dc)
		go dockLoop(conn, exer, dc, chDock, dclose)
	}
}

func main() {
	flag.Parse()
	if *printVer {
		fmt.Println(VERSION)
		return
	}
	MAX_DOCKS = *maxdocks
	docksAvail = make(chan uint, *maxdocks)
	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})
	for i := uint(0); i < MAX_DOCKS; i++ {
		docksAvail <- i
	}
	run()
}
