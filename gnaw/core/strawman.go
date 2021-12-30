package core

import (
	"context"
	"math"
	"os/exec"
	"os/user"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rs/zerolog/log"
)

const STRAWMANSPAN = 30 * time.Minute

var TIMEDUR = regexp.MustCompile(`(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)`)

type Strawman struct {
	n             int
	chScaleChange chan int
	controller    hpcController
}

func newStrawman(ctx context.Context, expectN int) (*Strawman, context.CancelFunc) {
	s := &Strawman{
		n:             expectN,
		chScaleChange: make(chan int),
		controller:    slurmController{}, // TODO: other HPC implementations
	}
	cctx, quit := context.WithCancel(ctx)
	go s.loop(cctx)
	return s, quit
}

func (s *Strawman) loop(ctx context.Context) {
	user, err := user.Current()
	if err != nil {
		panic(err)
	}
	username := user.Username

	quota := float64(s.n)
	period := float64(4 * 60 * 60) // average life cycle of workers, in seconds
	lastInterval := STRAWMANSPAN
	var lastCheck time.Time
	var lastStat map[string]hpcJobState
	for {
		currStat := s.controller.Stat(username)
		scaleAim := max(s.n-len(currStat), 0)
		scaleCap := min(scaleAim, int(math.Floor(quota)))
		if scaleCap > 0 {
			_ = exec.Command("grain", "up", "-n", strconv.Itoa(scaleCap)).Run()
			quota -= float64(scaleCap)
		}

		quota += float64(s.n) / (period / lastInterval.Seconds()) // ideally, we can restore the swarm at every life cycle
		for wid, sta := range lastStat {
			period = (period + sta.timeLimit) / 2
			if _, ok := currStat[wid]; ok {
				continue
			}
			quota *= (sta.timeElapsed + lastInterval.Seconds()) / sta.timeLimit // early exit penalty
		}
		lastCheck = time.Now()
		lastStat = currStat
		log.Debug().Float64("quota", quota).Msg("Strawman: current status")

		select {
		case <-time.After(STRAWMANSPAN):
		case newN := <-s.chScaleChange:
			jobs := s.controller.Stat(username)
			if newN < len(jobs) { // quit workers with shortest TTL
				for _, job := range sortJobByTTL(jobs)[:len(jobs)-newN] {
					if job.name != "n/a" {
						_ = exec.Command("grain", "quit", job.name).Run()
					} else {
						_ = s.controller.CancelJob(job.jid)
					}
				}
			}
			s.n = newN
		case <-ctx.Done():
			return
		}
		lastInterval = time.Since(lastCheck)
	}
}

func (s *Strawman) Scale(newN int) {
	s.chScaleChange <- newN
}

type (
	hpcController interface {
		Stat(string) map[string]hpcJobState
		CancelJob(string) error
	}
	hpcJobState struct {
		timeElapsed, timeLimit float64 // in seconds
		jid, name              string
	}

	slurmController struct{}
)

func (c slurmController) Stat(username string) map[string]hpcJobState {
	m := make(map[string]hpcJobState)
	output, err := exec.Command("squeue", "-o", "%i %B %M %l", "-u", username).Output()
	if err != nil {
		log.Error().Err(err).Msg("slurmController.Stat: error polling HPC queue information")
		return m
	}
	for _, l := range strings.Split(strings.TrimSpace(string(output)), "\n")[1:] {
		_f := strings.Fields(l)
		jid, name, elapsed, limit := _f[0], _f[1], _f[2], _f[3]
		m[jid] = hpcJobState{
			parseTimeDuration(elapsed), parseTimeDuration(limit),
			jid, name,
		}
	}
	return m
}

func (c slurmController) CancelJob(jid string) error {
	return exec.Command("scancel", jid).Run()
}

func sortJobByTTL(m map[string]hpcJobState) []hpcJobState {
	s := make([]hpcJobState, 0, len(m))
	for _, job := range m {
		s = append(s, job)
	}
	sort.Slice(s, func(i, j int) bool { return s[i].timeLimit-s[i].timeElapsed < s[j].timeLimit-s[j].timeElapsed })
	return s
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// parse a time str into a duration in seconds
func parseTimeDuration(raw string) (t float64) {
	_f := TIMEDUR.FindStringSubmatch(raw)
	d, h, m, s := _f[1], _f[2], _f[3], _f[4]
	if len(d) > 0 {
		d, _ := strconv.Atoi(d)
		t += float64(d) * 86400
	}
	if len(h) > 0 {
		h, _ := strconv.Atoi(h)
		t += float64(h) * 3600
	}
	m_, _ := strconv.Atoi(m)
	t += float64(m_) * 60
	s_, _ := strconv.Atoi(s)
	t += float64(s_)
	return
}
