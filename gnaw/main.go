package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/Contextualist/grain/gnaw/core"
	gnet "github.com/Contextualist/grain/gnaw/transport"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

const DOCK_COOLDOWN = 10 * time.Second

var (
	hurl        = flag.String("hurl", "", "URL for RemoteExers to connect")
	wurl        = flag.String("wurl", "", "URL for Workers to connect")
	maxdocks    = flag.Uint("n", 3, "Maximum numbers of RemoteExers allowed to connect")
	idleTimeout = flag.Duration("t", 8760*time.Hour, "Time to exit after the last RemoteExer quit")
	logfile     = flag.String("log", "", "Logfile location; leave blank for logging to stderr")
	swarm       = flag.Int("swarm", -1, "Expected size of worker swarm; -1 to disable autoscale")
	verbose     = flag.Bool("verbose", false, "Print out debug level log")
	printVer    = flag.Bool("version", false, "Print version and exit")

	VERSION    string // build-time injected
	MAX_DOCKS  uint
	docksAvail chan uint
	idleTimer  = time.NewTimer(8760 * time.Hour)
)

func dockLoop(conn net.Conn, hsmsg core.ControlMsg, exer *core.GrainExecutor, stager *core.SpecializedStager, dockID uint, chRet chan core.ResultMsg, dockClose func()) {
	chDone := make(chan struct{})
	defer func() {
		dockClose()
		_ = conn.Close()
		stager.RemoveFeedbackRemote(dockID)
		log.Info().Uint("dockID", dockID).Msg("RemoteExer quits")
		exer.Filter(func(tid uint) bool { return tid%MAX_DOCKS != dockID }) // discard all queued and running tasks
		time.Sleep(DOCK_COOLDOWN)
		docksAvail <- dockID
		log.Debug().Uint("dockID", dockID).Msg("Dock is now available")
		if len(docksAvail) == int(MAX_DOCKS) {
			idleTimer.Reset(*idleTimeout) // the timer is guarentee to be stopped before
		}
		close(chDone)
	}()

	bufException := make(chan core.ResultMsg, 32)
	go func() { // send results back
		snd := msgp.NewWriter(conn)
		err := stager.SendSynAck(snd, dockID)
		if err != nil {
			log.Error().Err(err).Uint("dockID", dockID).Msg("handshake SendSynAck failed")
		}
		for r := range chRet {
			if len(r.Exception) > 0 && r.Tid > 0 {
				bufException <- r
				continue
			}
			err := r.EncodeMsg(snd)
			if err != nil {
				break
			}
			err = snd.Flush()
			if err != nil {
				break
			}
		}
		for range chRet {
		} // drain
	}()

	go func() { // buffer exceptions
		var curExp *core.ResultMsg
		var count int
		send := func() {
			curExp.Tid = 0
			if count > 1 {
				curExp.Exception = fmt.Sprintf("%s (repeated %d times)", curExp.Exception, count)
			}
			chRet <- *curExp
		}
		var timeout <-chan time.Time
		for {
			select {
			case nxtExp := <-bufException:
				if curExp != nil {
					if nxtExp.Exception == curExp.Exception {
						count++
						continue
					}
					send()
				}
				curExp, count = &nxtExp, 1
				timeout = time.After(1 * time.Second) // wait for similar exception for up to 1s
			case <-timeout:
				send()
				curExp, count = nil, 0
				timeout = nil
			case <-chDone:
				return
			}
		}
	}()

	rcv := msgp.NewReader(conn)
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

func run(ctx context.Context) {
	stager := core.NewSpecializedStager()
	go stager.Run(ctx, func(gtid uint) (uint, uint) { return gtid % MAX_DOCKS, gtid / MAX_DOCKS })
	exer := core.NewGrainExecutor(ctx, *wurl, *swarm, stager)
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
	go func() {
		<-ctx.Done()
		exer.Close()
		ln.Close()
	}()
	for {
		conn, err := ln.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
			}
			if nerr, ok := err.(gnet.Error); ok && nerr.Temporary() {
				log.Error().Err(err).Msg("main.run: accept error")
				continue
			}
			panic(err)
		}

		// Handshakes:
		// frontend --cmd: chTaskResult, name: remote_name--> Gnaw
		// [Gnaw alloc a dock for frontend]
		// Gnaw --obj: { sworker_name: sworker_kws }, name: dock_id--> frontend
		// (optional) [frontend starts sremotes]
		// (optional) frontend --cmd: chApprovalFeedback, name: dock_id--> Gnaw
		rcv := msgp.NewReader(conn)
		var hsmsg core.ControlMsg
		err = hsmsg.DecodeMsg(rcv)
		logger := log.Error().Stringer("addr", conn.RemoteAddr())
		handleHandshakeErr := func(msg string, err ...error) bool {
			if len(err) == 1 {
				if err[0] == nil {
					return false
				}
				logger.Err(err[0]).Msg(msg)
			} else {
				logger.Msg(msg)
			}
			conn.Close()
			return true
		}
		if handleHandshakeErr("Error handling handshake from RemoteExer", err) {
			continue
		}
		switch hsmsg.Cmd {
		case "chApprovalRStatus":
			if hsmsg.Name == nil {
				handleHandshakeErr("handshake msg for chApprovalRStatus missing field Name")
				continue
			}
			dc_, err := strconv.Atoi(*hsmsg.Name)
			if dc_ < 0 {
				err = errors.New("expect a non-negative int")
			}
			if handleHandshakeErr("chApprovalRStatus handshake msg field Name is not an uint", err) {
				continue
			}
			dc := uint(dc_)
			stager.AddFeedbackRemote(dc, conn, func(rtid uint) uint { return rtid*MAX_DOCKS + dc })
			// Ack part of the handshake will be taken care by the feedback remote's sendLoop
			continue
		case "chTaskResult":
			// SynAck part of the handshake will be taken care after a dock is allocated.
		default:
			logger = logger.Str("cmd", hsmsg.Cmd)
			handleHandshakeErr("Unknown handshake command from RemoteExer")
			continue
		}

		var dc uint
		select {
		case dc = <-docksAvail:
		case <-ctx.Done():
			_ = conn.Close()
			return
		}
		idleTimer.Stop()
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
		go dockLoop(conn, hsmsg, exer, stager, dc, chDock, dclose)
	}
}

// In the case of idle timeout or signal interrupt, cancel the listeners, quit all workers, then exit
func cleanup(ctx context.Context, stop context.CancelFunc) {
	select {
	case <-idleTimer.C:
		stop()
	case <-ctx.Done():
	}
	time.Sleep(5 * time.Second) // worker quit is async, so give 5s grace period
	os.Exit(0)
}

func main() {
	flag.Parse()
	if *printVer {
		fmt.Println(VERSION)
		return
	}
	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}
	logwriter, noColor := os.Stderr, false
	if *logfile != "" {
		var err error
		logwriter, err = os.Create(*logfile)
		if err != nil {
			panic(err)
		}
		noColor = true
	}
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: logwriter, NoColor: noColor, TimeFormat: time.RFC3339})

	MAX_DOCKS = *maxdocks
	docksAvail = make(chan uint, MAX_DOCKS)
	for i := uint(0); i < MAX_DOCKS; i++ {
		docksAvail <- i
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	go run(ctx)
	cleanup(ctx, stop)
}
