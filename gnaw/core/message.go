package core

import "github.com/tinylib/msgp/msgp"

//go:generate msgp

type (
	ControlMsg struct {
		Cmd  string       `msg:"cmd"`
		Name *string      `msg:"name,omitempty"`
		Res  *PossibleRes `msg:"res,omitempty"`
	}

	FnMsg struct {
		Tid  uint        `msg:"tid"`
		Res  PossibleRes `msg:"res"`
		Func msgp.Raw    `msg:"func"`
	}

	ResultMsg struct {
		Tid       uint     `msg:"tid"`
		Exception string   `msg:"exception"`
		Result    msgp.Raw `msg:"result"`
	}

	PossibleRes struct {
		Cores  *struct{ N []uint } `msg:"Cores,omitempty"`
		Memory *struct{ M uint }   `msg:"Memory,omitempty"`
		WTime  *WTimeMsg           `msg:"WTime,omitempty"`
	}
	WTimeMsg struct {
		T         uint64
		SoftT     uint64 `msg:"softT"`
		Countdown bool   `msg:"countdown"`
	}
)

func ResFromMsg(rmsg *PossibleRes) Resource {
	rm := make(map[string]Resource)
	if rmsg.Cores != nil {
		rm["Cores"] = Cores(rmsg.Cores.N)
	}
	if rmsg.Memory != nil {
		rm["Memory"] = Memory(rmsg.Memory.M)
	}
	if rmsg.WTime != nil {
		rm["WTime"] = WTime(rmsg.WTime.T, rmsg.WTime.SoftT, rmsg.WTime.Countdown)
	}
	return &multiResource{rm}
}

func resToMsg(rm Resource) PossibleRes {
	rm_ := rm.(*multiResource) // NOTE: assumed multiResource
	pr := PossibleRes{}
	if c, ok := rm_.resm["Cores"]; ok {
		pr.Cores = &struct{ N []uint }{c.(*cores).c}
	}
	if m, ok := rm_.resm["Memory"]; ok {
		pr.Memory = &struct{ M uint }{m.(*memory).m}
	}
	if t, ok := rm_.resm["WTime"]; ok {
		t_ := t.(*wtime)
		pr.WTime = &WTimeMsg{T: uint64(t_.t.Seconds()), SoftT: uint64(t_.softT.Seconds())}
	}
	return pr
}
