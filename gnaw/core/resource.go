// This resource implementation focus on `Alloc`, and `Dealloc`
// functionalities. The internal values a resource struct hold are not
// designed to be accissible (because of the support of MultiResource).
package core

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Resource interface {
	Alloc(Resource) (Resource, bool)
	Dealloc(Resource)
	String() string
	Name() string
}

type memory struct {
	m, m0 uint
}

func Memory(m0 uint) *memory {
	return &memory{m: m0, m0: m0}
}
func (m *memory) Alloc(r Resource) (Resource, bool) {
	rm, ok := r.(*memory)
	if !ok || m.m < rm.m {
		return nil, false
	}
	m.m -= rm.m
	return rm, true
}
func (m *memory) Dealloc(r Resource) {
	m.m += r.(*memory).m
}
func (m *memory) String() string {
	return fmt.Sprintf("Memory(%dGB)", m.m)
}
func (m *memory) Name() string {
	return "Memory"
}

type cores struct {
	c  []uint
	n0 uint
}

func Cores(n0 interface{}) *cores {
	switch cn := n0.(type) {
	case uint:
		c := make([]uint, cn)
		var i uint
		for ; i < cn; i++ {
			c[i] = i
		}
		return &cores{c: c, n0: cn}
	case []uint:
		return &cores{c: cn, n0: uint(len(cn))}
	}
	return nil
}
func (c *cores) Alloc(r Resource) (Resource, bool) {
	rc, ok := r.(*cores)
	if !ok {
		return nil, false
	}
	cn := uint(len(c.c))
	if cn < rc.n0 {
		return nil, false
	}
	an := rc.n0
	ac := make([]uint, an)
	copy(ac, c.c[cn-an:])
	c.c = c.c[:cn-an]
	return Cores(ac), true
}
func (c *cores) Dealloc(r Resource) {
	c.c = append(c.c, r.(*cores).c...)
}
func (c *cores) String() string {
	con := [][]uint{{c.c[0], c.c[0]}}
	for _, x := range c.c[1:] {
		if x == con[len(con)-1][1]+1 {
			con[len(con)-1][1] = x
		} else {
			con = append(con, []uint{x, x})
		}
	}
	r := make([]string, len(con))
	for i, tup := range con {
		if tup[0] == tup[1] {
			r[i] = strconv.Itoa(int(tup[0]))
		} else {
			r[i] = strconv.Itoa(int(tup[0])) + "-" + strconv.Itoa(int(tup[1]))
		}
	}
	return fmt.Sprintf("Cores([%s])", strings.Join(r, ","))
}
func (c *cores) Name() string {
	return "Cores"
}

const (
	TIMESTAT_NSAMPLE = 8
	MAXDURATION      = 100 * 365 * 24 * time.Hour
)

var (
	// NOTE: currently assuming single-thread access, so no lock
	timestat = make(map[string][]float64)
	timeinfr = make(map[string]*wtime)
)

type wtime struct {
	t, softT time.Duration
	group    string
	deadline time.Time
}

func WTime(t, softT uint64, group string, countdown bool) *wtime {
	if softT == 0 {
		softT = t
	}
	t_, st_ := time.Duration(t)*time.Second, time.Duration(softT)*time.Second
	var dl time.Time
	if countdown {
		dl = time.Now().Add(t_)
	}
	return &wtime{t_, st_, group, dl}
}
func (t *wtime) Alloc(r Resource) (Resource, bool) {
	rt, ok := r.(*wtime)
	if !ok {
		return nil, false
	}
	if group := rt.group; group != "" {
		rt, ok = timeinfr[group]
		if !ok { // record current time for sampling
			return &wtime{MAXDURATION, MAXDURATION, group, time.Now()}, true
		}
	}
	if time.Until(t.deadline) < rt.softT {
		return nil, false
	}
	return rt, true
}
func (t *wtime) Dealloc(r Resource) {
	rt, ok := r.(*wtime)
	if !ok || rt.group == "" || timeinfr[rt.group] != nil {
		return
	}
	delt := time.Since(rt.deadline)
	if delt < 10*time.Second {
		// 1. A rewind in multiresource alloc attempt is almost instant
		// 2. Could be a premature end due to an early fatal error
		// 3. Timeout is less useful for short jobs
		return
	}
	timestat[rt.group] = append(timestat[rt.group], delt.Seconds())
	if len(timestat[rt.group]) == TIMESTAT_NSAMPLE {
		tm, ts := mean_std(timestat[rt.group])
		timeinfr[rt.group] = &wtime{t: time.Duration(tm+5*ts) * time.Second, softT: time.Duration(tm+2*ts) * time.Second}
		delete(timestat, rt.group)
	}
}
func (t *wtime) String() string {
	var d uint64
	if t.group != "" {
		if t_, ok := timeinfr[t.group]; ok {
			return t_.String()
		}
		return fmt.Sprintf("Walltime(group=%s)", t.group)
	}
	if t.deadline.IsZero() {
		d = uint64(t.t.Seconds())
	} else {
		d = uint64(time.Until(t.deadline).Seconds())
	}
	return fmt.Sprintf("Walltime(%02d:%02d:%02d)", d/3600, d%3600/60, d%60)
}
func (t *wtime) Name() string {
	return "WTime"
}
func mean_std(s []float64) (float64, float64) {
	var m, v float64
	for _, x := range s {
		m += x
	}
	m /= float64(len(s))
	for _, x := range s {
		v += (x - m) * (x - m)
	}
	return m, math.Sqrt(v / float64((len(s) - 1)))
}

type multiResource struct {
	resm map[string]Resource
}

func And(rs ...Resource) *multiResource {
	return MultiResource(rs)
}
func MultiResource(rs []Resource) *multiResource {
	resm := make(map[string]Resource)
	for _, r := range rs {
		if mr, ok := r.(*multiResource); ok {
			for name, s := range mr.resm {
				resm[name] = s
			}
		} else {
			resm[r.Name()] = r
		}
	}
	return &multiResource{
		resm,
	}
}
func (m *multiResource) Alloc(r Resource) (Resource, bool) {
	rm, ok := r.(*multiResource)
	if !ok {
		return nil, false
	}
	am := make(map[string]Resource)
	for name, s := range rm.resm {
		if x, ok := m.resm[name]; ok {
			if s, ok := x.Alloc(s); ok {
				am[name] = s
				continue
			}
		}
		for name, s := range am {
			m.resm[name].Dealloc(s)
		}
		return nil, false
	}
	return &multiResource{am}, true
}
func (m *multiResource) Dealloc(r Resource) {
	for name, s := range r.(*multiResource).resm {
		m.resm[name].Dealloc(s)
	}
}
func (m *multiResource) String() string {
	names := make([]string, 0, len(m.resm))
	for k := range m.resm {
		names = append(names, k)
	}
	sort.Strings(names)
	var b strings.Builder
	b.WriteString(m.resm[names[0]].String())
	for _, k := range names[1:] {
		fmt.Fprintf(&b, " & %s", m.resm[k].String())
	}
	return b.String()
}
func (m *multiResource) Name() string {
	return "MultiResource"
}
