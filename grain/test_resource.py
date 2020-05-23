from .resource import *

import pytest

def test_zero():
    # repr
    assert str(ZERO) == "Ø"
    # request, alloc
    assert ZERO.request(ZERO)
    assert str(ZERO.alloc(ZERO)) == "Ø"
    some = Node(1,1)
    assert some.request(ZERO)
    assert str(some.alloc(ZERO)) == "Ø"
    assert ZERO.request(some) is False
    with pytest.raises(ValueError, match="Cannot alloc"):
        ZERO.alloc(some)

def test_cores():
    # repr
    assert str(Cores(3)) == "CPU_Cores([0-2])"
    assert str(Cores([5,7,8])) == "CPU_Cores([5,7-8])"
    # request, alloc
    c0 = Cores(16)
    assert c0.request(Cores(16))
    assert c0.request(Cores(17)) is False
    with pytest.raises(ValueError, match=r"cannot allocate .* core\(s\)"):
        c0.alloc(Cores(17))
    a = c0.alloc(Cores(3))
    assert len(a.c)==3 and a.c&c0.c==set()
    assert c0.request(Cores(14)) is False
    # dealloc
    c0.dealloc(a)
    assert len(c0.c)==c0.N==16

def test_memory():
    # repr
    assert str(Memory(16)) == "Memory(16GB)"
    # request, alloc
    m0 = Memory(64)
    assert m0.request(Memory(64))
    assert m0.request(Memory(65)) is False
    with pytest.raises(ValueError, match="cannot allocate"):
        m0.alloc(Memory(65))
    a = m0.alloc(Memory(16))
    assert a.m==16 and a.m+m0.m==64
    assert m0.request(Memory(50)) is False
    # dealloc
    m0.dealloc(a)
    assert m0.m==m0.M==64

def test_walltime(monkeypatch):
    import time
    monkeypatch.setattr(time, "time", lambda: now) # mock timestamp
    # repr
    now = 0.0
    t0, t1, t2 = WTime("1:56:40"), WTime(7000), WTime(7000, countdown=True)
    now += 2.0
    assert str(t0)==str(t1)=="Walltime(01:56:40)" and str(t2)=="Walltime(01:56:38)"
    # request, alloc
    now = 0.0
    t2 = WTime(30, countdown=True)
    assert t2.request(WTime(30))
    now += 2.0
    assert t2.request(WTime(29)) is False
    assert t2.alloc(WTime(3)).T == 3

def test_token():
    # repr
    assert str(Token('A')) == "Token(A)"
    # request, alloc
    a = Token('A')
    assert a.request(Token('A'))
    assert a.request(Token('B')) is False
    assert a.alloc(Token('A')) == a
    assert a.request(Token('A'))

def test_capacity():
    # repr
    assert str(Capacity(0)) == "Capacity(0)"
    assert str(ONE_INSTANCE) == "ONE"
    # request, alloc
    c = Capacity(1)
    assert c.request(ONE_INSTANCE)
    assert c.alloc(ONE_INSTANCE).v == -1
    assert c.v==0
    with pytest.raises(ValueError, match="has no capacity"):
        c.alloc(ONE_INSTANCE)
    # dealloc
    c.dealloc(ONE_INSTANCE)
    assert c.v==c.V==1

def test_reject():
    # request
    assert REJECT.request(ZERO) is False
    r = Reject(Memory(8))
    r.dealloc(Memory(4))
    assert r.request(Memory(8)) is False
    # eject
    assert r.eject() == Memory(12)

def test_multiresource():
    # repr
    assert str(Cores(3) & Memory(16)) == "CPU_Cores([0-2]) & Memory(16GB)"
    # request, alloc
    r = Cores(6) & Memory(16)
    assert r.request(Memory(8))
    assert r.request(Cores(3) & Memory(8))
    assert r.request(Cores(9)) is False
    assert r.request(Cores(3) & Memory(17)) is False
    with pytest.raises(ValueError, match="cannot allocate"):
        r.alloc(Cores(3) & Memory(17))
    with pytest.raises(ValueError, match="does not have the same shape"):
        r.alloc(WTime(3))
    a = r.alloc(Cores(3) & Memory(8))
    assert len(a.c)==3 and a.m==8 and len(a.c|r.c)==6 and a.m+r.m==16
    assert r.request(Cores(3) & Memory(9)) is False
    # dealloc
    r.dealloc(a)
    assert len(r.c)==r.N==6 and r.m==r.M==16

def test_res2link0():
    assert res2link0(Cores([5,7,8]) & Memory(16)) == "%CPU=5,7,8\n%Mem=16GB\n"
    assert res2link0(Memory(16)) == "%Mem=16GB\n"
    assert res2link0(ZERO) == ""
