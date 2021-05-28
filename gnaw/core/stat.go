package core

import (
	"fmt"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog/log"
)

const STATSPAN = 15 * time.Minute

type Stat struct {
	completed          uint64
	exception          uint64
	lateResponse       uint64
	lostOrLateResponse uint64
}

func (s *Stat) Reset() *Stat {
	s0 := new(Stat)
	s0.completed = atomic.SwapUint64(&s.completed, 0)
	s0.exception = atomic.SwapUint64(&s.exception, 0)
	s0.lateResponse = atomic.SwapUint64(&s.lateResponse, 0)
	s0.lostOrLateResponse = atomic.SwapUint64(&s.lostOrLateResponse, 0)
	return s0
}

func (s *Stat) Log() {
	r := s.Reset()
	b := new(strings.Builder)
	b.WriteString("STAT: ")
	if r.completed > 0 {
		fmt.Fprintf(b, "completed: %d\t", r.completed)
	}
	if r.exception > 0 {
		fmt.Fprintf(b, "error: %d\t", r.exception)
	}
	if r.lateResponse > 0 {
		fmt.Fprintf(b, "late_response: %d\t", r.lateResponse)
	}
	if lost := r.lostOrLateResponse - r.lateResponse; lost > 0 {
		fmt.Fprintf(b, "lost_response: %d\t", lost)
	}
	if b.Len() > 0 {
		log.Info().Msg(b.String())
	}
}

func StatLoop() {
	for range time.Tick(STATSPAN) {
		DefaultStat.Log()
	}
}

func workerStatistics(ws []*Remote) *strings.Builder {
	s := new(strings.Builder)
	nameLen := 5
	for _, w := range ws {
		if l := len(w.name); l > nameLen {
			nameLen = l
		}
	}
	nameLen += 4
	FMT := "%" + strconv.Itoa(nameLen) + "s%10s%10s%8s\n"
	fmt.Fprintf(s, FMT, "", "Cores", "Memory", "")
	var cAvail int
	var cTotal, mAvail, mTotal uint
	for _, w := range ws {
		r := w.res.(*multiResource).resm // NOTE: assume multiresource
		c, m := r["Cores"].(*cores), r["Memory"].(*memory)
		p := ""
		if w.closing {
			p = "paused"
		}
		fmt.Fprintf(s, FMT,
			w.name,
			fmt.Sprintf("%d/%d", len(c.c), c.n0),
			fmt.Sprintf("%d/%d", m.m, m.m0),
			p,
		)
		cAvail += len(c.c)
		cTotal += c.n0
		mAvail += m.m
		mTotal += m.m0
	}
	fmt.Fprintf(s, FMT,
		"TOTAL",
		fmt.Sprintf("%d/%d", cAvail, cTotal),
		fmt.Sprintf("%d/%d", mAvail, mTotal),
		"",
	)
	fmt.Fprintln(s)
	return s
}

var DefaultStat *Stat

func init() {
	DefaultStat = new(Stat)
	go StatLoop()
}
