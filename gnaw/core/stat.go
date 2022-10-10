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
	if b.Len() > 6 {
		log.Info().Msg(b.String())
	}
}

func StatLoop() {
	for range time.Tick(STATSPAN) {
		DefaultStat.Log()
	}
}

func workerStatistics(ws []IRemote) *strings.Builder {
	// Stat and render each cell
	type winfo struct {
		name   string
		resstr map[string]string
		note   string
	}
	var rows []winfo
	nameLen := 5
	total := make(map[string][]uint)
	for _, w := range ws {
		if l := len(w.getName()); l > nameLen {
			nameLen = l
		}
		r := w.getRes().(*multiResource).resm // NOTE: assume multiresource
		resstr := make(map[string]string, len(r))
		for rname, rx := range r {
			avail, bound := rx.Stat()
			if bound == 0 {
				continue
			}
			resstr[rname] = fmt.Sprintf("%d/%d", avail, bound)
			if t, ok := total[rname]; ok {
				t[0] += avail
				t[1] += bound
			} else {
				total[rname] = []uint{avail, bound}
			}
		}
		note := ""
		if w.isClosing() {
			note = "paused"
		}
		rows = append(rows, winfo{w.getName(), resstr, note})
	}
	totalstr := make([]string, 0, len(total))
	for _, tot := range total {
		totalstr = append(totalstr, fmt.Sprintf("%d/%d", tot[0], tot[1]))
	}

	// Align and format the table
	s := new(strings.Builder)
	nameLen += 4
	fields := mapKeys(total)
	FMT := "%" + strconv.Itoa(nameLen) + "s" + strings.Repeat("%10s", len(fields)) + "%8s\n"
	fmt.Fprintf(s, FMT, rowSlice("", fields, "")...)
	for _, wi := range rows {
		resstr := make([]string, 0, len(fields))
		for _, field := range fields {
			if s, ok := wi.resstr[field]; ok {
				resstr = append(resstr, s)
			} else {
				resstr = append(resstr, "")
			}
		}
		fmt.Fprintf(s, FMT, rowSlice(wi.name, resstr, wi.note)...)
	}
	if len(totalstr) > 0 {
		fmt.Fprintf(s, FMT, rowSlice("TOTAL", totalstr, "")...)
	} else {
		fmt.Fprintf(s, "No worker is currently connected\n")
	}
	fmt.Fprintln(s)
	return s
}

func mapKeys[K comparable, V any](m map[K]V) []K {
	keys := make([]K, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}

func rowSlice(name string, rs []string, note string) []interface{} {
	r := make([]interface{}, 1+len(rs)+1)
	r[0] = name
	for i := range rs {
		r[i+1] = rs[i]
	}
	r[1+len(rs)] = note
	return r
}

var DefaultStat *Stat

func init() {
	DefaultStat = new(Stat)
	go StatLoop()
}
