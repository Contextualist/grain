package core

import (
	"context"
	"errors"
	"io"
	"net"
	"strconv"
	"sync"

	"github.com/rs/zerolog/log"
	"github.com/tinylib/msgp/msgp"
)

//           FnMsg (no payload)
// frontend ----------------------> Gnaw.SpecializedRemote
//                                     | FnMsg (approval stub)
//           FnMsg (approval stub)     v
// frontend <---------------------- Gnaw.feedbackRemote
//
//                                  Gnaw.SpecializedRemote
//                                     ^
//           ResultMsg (rstatus stub)  | ResultMsg (rstatus stub)
// frontend ----------------------> Gnaw.feedbackRemote

type (
	// Manage all channels for the specialized remotes' approval-rstatus workflow
	// and all feedbackRemote instances
	SpecializedStager struct {
		// multiplexed queue for approval messages from all SpecializedRemotes
		approvalMux chan FnMsg

		muA sync.RWMutex
		// Approval message queues for the feedbackRemotes
		chApprovals map[uint]chan<- FnMsg
		// list of feedbackRemotes
		feedbacks map[uint]*feedbackRemote

		// multiplexed queue for result status messages from all feedbackRemotes
		rstatusMux chan ResultMsg

		muR sync.RWMutex
		// Result status messgage queues for the SpecializedRemotes
		chRStatus map[string]chan<- ResultMsg
		// register kwargs for all current SpecializedRemotes
		sworkerArgs map[string]msgp.Raw
	}

	tidExportFn func(uint) (uint, uint) // turn a Gnaw-side tid to RemoteExer's ID and RemoteExer-side tid
	tidImportFn func(uint) uint         // for a speciafic RemoteExer, turn RemoteExer-side tid to a Gnaw-side tid

)

func NewSpecializedStager() *SpecializedStager {
	return &SpecializedStager{
		approvalMux: make(chan FnMsg),
		chApprovals: make(map[uint]chan<- FnMsg),
		feedbacks:   make(map[uint]*feedbackRemote),
		rstatusMux:  make(chan ResultMsg),
		chRStatus:   make(map[string]chan<- ResultMsg),
		sworkerArgs: make(map[string]msgp.Raw),
	}
}

func (s *SpecializedStager) Run(ctx context.Context, exportTid tidExportFn) {

	go func() { // relay approval stub from SpecializedRemotes to feedbackRemotes
		for r := range s.approvalMux {
			cid, tid := exportTid(r.Tid)
			s.muA.RLock()
			c, ok := s.chApprovals[cid]
			if !ok {
				log.Info().Uint("ID", cid).Msg("Approval stub for quitted end")
				s.muA.RUnlock()
				continue
			}
			r.Tid = tid
			c <- r
			s.muA.RUnlock()
		}
	}()

	go func() { // relay result status stub from feedbackRemotes to SpecializedRemotes
		for r := range s.rstatusMux {
			// r.Tid has been imported
			name, _, err := msgp.ReadStringBytes(r.Result)
			if err != nil {
				log.Error().Uint("tid", r.Tid).Msg("Invalid rstatus stub")
			}
			s.muR.RLock()
			c, ok := s.chRStatus[name]
			if !ok {
				log.Info().Str("name", name).Msg("Rstatus stub for quitted end")
				s.muR.RUnlock()
				continue
			}
			c <- r
			s.muR.RUnlock()
		}
	}()

	<-ctx.Done()
	// TODO: should we wait for all feedbackR / SpecializedR?
	//close(s.approvalMux)
	//close(s.rstatusMux)
}

func (s *SpecializedStager) AddFeedbackRemote(id uint, conn net.Conn, importTid tidImportFn) {
	chA := make(chan FnMsg, 16)
	r := newFeedbackRemote(id, importTid, conn, chA, s.rstatusMux)
	s.muA.Lock()
	s.chApprovals[id] = chA
	s.feedbacks[id] = r
	s.muA.Unlock()
	s.sendAck(r.sender)
	go r.sendLoop()
	go r.recvLoop()
}

func (s *SpecializedStager) RemoveFeedbackRemote(id uint) {
	s.muA.Lock()
	if _, ok := s.chApprovals[id]; !ok {
		s.muA.Unlock()
		return
	}
	close(s.chApprovals[id])
	delete(s.chApprovals, id)
	s.feedbacks[id].close()
	delete(s.feedbacks, id)
	s.muA.Unlock()
}

func (s *SpecializedStager) addSpecializedRemote(name string, res Resource, obj msgp.Raw, mgr ResourceManager, retryq chan<- Task, conn net.Conn) *SpecializedRemote {
	chR := make(chan ResultMsg, 16)
	s.muR.Lock()
	if _, ok := s.chRStatus[name]; ok { // we could receive the same reg request for backendless sworker from multiple frontends
		s.muR.Unlock()
		return nil
	}
	s.chRStatus[name] = chR
	s.sworkerArgs[name] = obj
	s.announceSpecializedRemote(name, obj) // let frontend start the sworker client before making this sworker available
	s.muR.Unlock()
	r := newSpecializedRemote(name, res, mgr, retryq, conn, s.approvalMux, chR, func() { s.removeSpecializedRemote(name) })
	return r
}

func (s *SpecializedStager) removeSpecializedRemote(name string) {
	s.muR.Lock()
	close(s.chRStatus[name])
	delete(s.chRStatus, name)
	delete(s.sworkerArgs, name)
	s.notifyQuitSpecializedRemote(name)
	s.muR.Unlock()
}

// Inform frontend about its asociated ID
func (s *SpecializedStager) SendSynAck(snd *msgp.Writer, id uint) (err error) {
	name := strconv.Itoa(int(id))
	if err = (&ControlMsg{Cmd: "hsSynAck", Name: &name}).EncodeMsg(snd); err != nil {
		return
	}
	if err = snd.Flush(); err != nil {
		return
	}
	return
}

// Inform frontend about currently connected SpecializedRemote
func (s *SpecializedStager) sendAck(snd *msgp.Writer) (err error) {
	s.muR.RLock()
	defer s.muR.RUnlock()
	o := msgp.AppendMapHeader(nil, uint32(len(s.sworkerArgs)))
	for name, raw := range s.sworkerArgs {
		o = msgp.AppendString(o, name)
		o, err = raw.MarshalMsg(o)
		if err != nil {
			err = msgp.WrapError(err, "obj", name)
			return
		}
	}
	obj := msgp.Raw(o)
	if err = (&ControlMsg{Cmd: "hsAck", Obj: &obj}).EncodeMsg(snd); err != nil {
		return
	}
	if err = snd.Flush(); err != nil {
		return
	}
	return
}

// Inform all frontends about a recently connected SpecializedRemote
func (s *SpecializedStager) announceSpecializedRemote(name string, obj msgp.Raw) {
	s.muA.RLock()
	defer s.muA.RUnlock()
	for _, fb := range s.feedbacks {
		if err := fb.announceSpecializedRemote(name, obj); err != nil {
			log.Warn().Err(err).Uint("id", fb.id).Msg("Failed to announce specialized remote to a feedback remote")
		}
	}
}

// Inform all frontends about a recently quitted SpecializedRemote
func (s *SpecializedStager) notifyQuitSpecializedRemote(name string) {
	s.muA.RLock()
	defer s.muA.RUnlock()
	for _, fb := range s.feedbacks {
		if err := fb.notifyQuitSpecializedRemote(name); err != nil {
			log.Warn().Err(err).Uint("id", fb.id).Msg("Failed to notify on a quitted specialized remote to a feedback remote")
		}
	}
}

type (
	// It looks like a remote, but if you look closer, it's facing the other direction!
	feedbackRemote struct {
		id uint

		chApproval <-chan FnMsg
		rstatusq   chan<- ResultMsg
		mu         sync.Mutex
		conn       net.Conn
		sender     *msgp.Writer
		closing    bool

		importTid tidImportFn
	}
)

func newFeedbackRemote(id uint, importTid tidImportFn, conn net.Conn, chApproval chan FnMsg, rstatusq chan ResultMsg) *feedbackRemote {
	return &feedbackRemote{
		id:         id,
		chApproval: chApproval,
		rstatusq:   rstatusq,
		conn:       conn,
		sender:     msgp.NewWriter(conn),
		importTid:  importTid,
	}
}

func (w *feedbackRemote) sendLoop() {
	logger := log.Error().Uint("id", w.id)
	for t := range w.chApproval {
		w.mu.Lock()
		err := t.EncodeMsg(w.sender)
		if err != nil {
			w.mu.Unlock()
			if !w.closing {
				logger.Err(err).Msg("feedbackRemote.sendLoop: write error")
			}
			return
		}
		err = w.sender.Flush()
		if err != nil {
			w.mu.Unlock()
			if !w.closing {
				logger.Err(err).Msg("feedbackRemote.sendLoop: flush error")
			}
			return
		}
		w.mu.Unlock()
	}
}

func (w *feedbackRemote) recvLoop() {
	receiver := msgp.NewReader(w.conn)
	for {
		var r ResultMsg
		err := r.DecodeMsg(receiver)
		if err != nil {
			if !w.closing && !errors.Is(err, io.EOF) {
				log.Error().Uint("id", w.id).Err(err).Msg("feedbackRemote.recvLoop: read error")
			}
			return
		}

		r.Tid = w.importTid(r.Tid)
		w.rstatusq <- r
	}
}

func (w *feedbackRemote) close() {
	w.closing = true
	_ = w.conn.Close()
}

func (w *feedbackRemote) announceSpecializedRemote(name string, obj msgp.Raw) (err error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if err = (&ControlMsg{Cmd: "pushSWorker", Name: &name, Obj: &obj}).EncodeMsg(w.sender); err != nil {
		return
	}
	if err = w.sender.Flush(); err != nil {
		return
	}
	return
}

func (w *feedbackRemote) notifyQuitSpecializedRemote(name string) (err error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if err = (&ControlMsg{Cmd: "quitSWorker", Name: &name}).EncodeMsg(w.sender); err != nil {
		return
	}
	if err = w.sender.Flush(); err != nil {
		return
	}
	return
}
