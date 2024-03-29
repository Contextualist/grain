package core

// Code generated by github.com/tinylib/msgp DO NOT EDIT.

import (
	"github.com/tinylib/msgp/msgp"
)

// DecodeMsg implements msgp.Decodable
func (z *ControlMsg) DecodeMsg(dc *msgp.Reader) (err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, err = dc.ReadMapHeader()
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, err = dc.ReadMapKeyPtr()
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "cmd":
			z.Cmd, err = dc.ReadString()
			if err != nil {
				err = msgp.WrapError(err, "Cmd")
				return
			}
		case "name":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Name")
					return
				}
				z.Name = nil
			} else {
				if z.Name == nil {
					z.Name = new(string)
				}
				*z.Name, err = dc.ReadString()
				if err != nil {
					err = msgp.WrapError(err, "Name")
					return
				}
			}
		case "res":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Res")
					return
				}
				z.Res = nil
			} else {
				if z.Res == nil {
					z.Res = new(PossibleRes)
				}
				err = z.Res.DecodeMsg(dc)
				if err != nil {
					err = msgp.WrapError(err, "Res")
					return
				}
			}
		case "obj":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Obj")
					return
				}
				z.Obj = nil
			} else {
				if z.Obj == nil {
					z.Obj = new(msgp.Raw)
				}
				err = z.Obj.DecodeMsg(dc)
				if err != nil {
					err = msgp.WrapError(err, "Obj")
					return
				}
			}
		default:
			err = dc.Skip()
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	return
}

// EncodeMsg implements msgp.Encodable
func (z *ControlMsg) EncodeMsg(en *msgp.Writer) (err error) {
	// omitempty: check for empty values
	zb0001Len := uint32(4)
	var zb0001Mask uint8 /* 4 bits */
	if z.Name == nil {
		zb0001Len--
		zb0001Mask |= 0x2
	}
	if z.Res == nil {
		zb0001Len--
		zb0001Mask |= 0x4
	}
	if z.Obj == nil {
		zb0001Len--
		zb0001Mask |= 0x8
	}
	// variable map header, size zb0001Len
	err = en.Append(0x80 | uint8(zb0001Len))
	if err != nil {
		return
	}
	if zb0001Len == 0 {
		return
	}
	// write "cmd"
	err = en.Append(0xa3, 0x63, 0x6d, 0x64)
	if err != nil {
		return
	}
	err = en.WriteString(z.Cmd)
	if err != nil {
		err = msgp.WrapError(err, "Cmd")
		return
	}
	if (zb0001Mask & 0x2) == 0 { // if not empty
		// write "name"
		err = en.Append(0xa4, 0x6e, 0x61, 0x6d, 0x65)
		if err != nil {
			return
		}
		if z.Name == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			err = en.WriteString(*z.Name)
			if err != nil {
				err = msgp.WrapError(err, "Name")
				return
			}
		}
	}
	if (zb0001Mask & 0x4) == 0 { // if not empty
		// write "res"
		err = en.Append(0xa3, 0x72, 0x65, 0x73)
		if err != nil {
			return
		}
		if z.Res == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			err = z.Res.EncodeMsg(en)
			if err != nil {
				err = msgp.WrapError(err, "Res")
				return
			}
		}
	}
	if (zb0001Mask & 0x8) == 0 { // if not empty
		// write "obj"
		err = en.Append(0xa3, 0x6f, 0x62, 0x6a)
		if err != nil {
			return
		}
		if z.Obj == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			err = z.Obj.EncodeMsg(en)
			if err != nil {
				err = msgp.WrapError(err, "Obj")
				return
			}
		}
	}
	return
}

// MarshalMsg implements msgp.Marshaler
func (z *ControlMsg) MarshalMsg(b []byte) (o []byte, err error) {
	o = msgp.Require(b, z.Msgsize())
	// omitempty: check for empty values
	zb0001Len := uint32(4)
	var zb0001Mask uint8 /* 4 bits */
	if z.Name == nil {
		zb0001Len--
		zb0001Mask |= 0x2
	}
	if z.Res == nil {
		zb0001Len--
		zb0001Mask |= 0x4
	}
	if z.Obj == nil {
		zb0001Len--
		zb0001Mask |= 0x8
	}
	// variable map header, size zb0001Len
	o = append(o, 0x80|uint8(zb0001Len))
	if zb0001Len == 0 {
		return
	}
	// string "cmd"
	o = append(o, 0xa3, 0x63, 0x6d, 0x64)
	o = msgp.AppendString(o, z.Cmd)
	if (zb0001Mask & 0x2) == 0 { // if not empty
		// string "name"
		o = append(o, 0xa4, 0x6e, 0x61, 0x6d, 0x65)
		if z.Name == nil {
			o = msgp.AppendNil(o)
		} else {
			o = msgp.AppendString(o, *z.Name)
		}
	}
	if (zb0001Mask & 0x4) == 0 { // if not empty
		// string "res"
		o = append(o, 0xa3, 0x72, 0x65, 0x73)
		if z.Res == nil {
			o = msgp.AppendNil(o)
		} else {
			o, err = z.Res.MarshalMsg(o)
			if err != nil {
				err = msgp.WrapError(err, "Res")
				return
			}
		}
	}
	if (zb0001Mask & 0x8) == 0 { // if not empty
		// string "obj"
		o = append(o, 0xa3, 0x6f, 0x62, 0x6a)
		if z.Obj == nil {
			o = msgp.AppendNil(o)
		} else {
			o, err = z.Obj.MarshalMsg(o)
			if err != nil {
				err = msgp.WrapError(err, "Obj")
				return
			}
		}
	}
	return
}

// UnmarshalMsg implements msgp.Unmarshaler
func (z *ControlMsg) UnmarshalMsg(bts []byte) (o []byte, err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, bts, err = msgp.ReadMapHeaderBytes(bts)
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, bts, err = msgp.ReadMapKeyZC(bts)
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "cmd":
			z.Cmd, bts, err = msgp.ReadStringBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Cmd")
				return
			}
		case "name":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Name = nil
			} else {
				if z.Name == nil {
					z.Name = new(string)
				}
				*z.Name, bts, err = msgp.ReadStringBytes(bts)
				if err != nil {
					err = msgp.WrapError(err, "Name")
					return
				}
			}
		case "res":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Res = nil
			} else {
				if z.Res == nil {
					z.Res = new(PossibleRes)
				}
				bts, err = z.Res.UnmarshalMsg(bts)
				if err != nil {
					err = msgp.WrapError(err, "Res")
					return
				}
			}
		case "obj":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Obj = nil
			} else {
				if z.Obj == nil {
					z.Obj = new(msgp.Raw)
				}
				bts, err = z.Obj.UnmarshalMsg(bts)
				if err != nil {
					err = msgp.WrapError(err, "Obj")
					return
				}
			}
		default:
			bts, err = msgp.Skip(bts)
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	o = bts
	return
}

// Msgsize returns an upper bound estimate of the number of bytes occupied by the serialized message
func (z *ControlMsg) Msgsize() (s int) {
	s = 1 + 4 + msgp.StringPrefixSize + len(z.Cmd) + 5
	if z.Name == nil {
		s += msgp.NilSize
	} else {
		s += msgp.StringPrefixSize + len(*z.Name)
	}
	s += 4
	if z.Res == nil {
		s += msgp.NilSize
	} else {
		s += z.Res.Msgsize()
	}
	s += 4
	if z.Obj == nil {
		s += msgp.NilSize
	} else {
		s += z.Obj.Msgsize()
	}
	return
}

// DecodeMsg implements msgp.Decodable
func (z *FnMsg) DecodeMsg(dc *msgp.Reader) (err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, err = dc.ReadMapHeader()
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, err = dc.ReadMapKeyPtr()
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "tid":
			z.Tid, err = dc.ReadUint()
			if err != nil {
				err = msgp.WrapError(err, "Tid")
				return
			}
		case "res":
			err = z.Res.DecodeMsg(dc)
			if err != nil {
				err = msgp.WrapError(err, "Res")
				return
			}
		case "func":
			err = z.Func.DecodeMsg(dc)
			if err != nil {
				err = msgp.WrapError(err, "Func")
				return
			}
		default:
			err = dc.Skip()
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	return
}

// EncodeMsg implements msgp.Encodable
func (z *FnMsg) EncodeMsg(en *msgp.Writer) (err error) {
	// map header, size 3
	// write "tid"
	err = en.Append(0x83, 0xa3, 0x74, 0x69, 0x64)
	if err != nil {
		return
	}
	err = en.WriteUint(z.Tid)
	if err != nil {
		err = msgp.WrapError(err, "Tid")
		return
	}
	// write "res"
	err = en.Append(0xa3, 0x72, 0x65, 0x73)
	if err != nil {
		return
	}
	err = z.Res.EncodeMsg(en)
	if err != nil {
		err = msgp.WrapError(err, "Res")
		return
	}
	// write "func"
	err = en.Append(0xa4, 0x66, 0x75, 0x6e, 0x63)
	if err != nil {
		return
	}
	err = z.Func.EncodeMsg(en)
	if err != nil {
		err = msgp.WrapError(err, "Func")
		return
	}
	return
}

// MarshalMsg implements msgp.Marshaler
func (z *FnMsg) MarshalMsg(b []byte) (o []byte, err error) {
	o = msgp.Require(b, z.Msgsize())
	// map header, size 3
	// string "tid"
	o = append(o, 0x83, 0xa3, 0x74, 0x69, 0x64)
	o = msgp.AppendUint(o, z.Tid)
	// string "res"
	o = append(o, 0xa3, 0x72, 0x65, 0x73)
	o, err = z.Res.MarshalMsg(o)
	if err != nil {
		err = msgp.WrapError(err, "Res")
		return
	}
	// string "func"
	o = append(o, 0xa4, 0x66, 0x75, 0x6e, 0x63)
	o, err = z.Func.MarshalMsg(o)
	if err != nil {
		err = msgp.WrapError(err, "Func")
		return
	}
	return
}

// UnmarshalMsg implements msgp.Unmarshaler
func (z *FnMsg) UnmarshalMsg(bts []byte) (o []byte, err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, bts, err = msgp.ReadMapHeaderBytes(bts)
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, bts, err = msgp.ReadMapKeyZC(bts)
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "tid":
			z.Tid, bts, err = msgp.ReadUintBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Tid")
				return
			}
		case "res":
			bts, err = z.Res.UnmarshalMsg(bts)
			if err != nil {
				err = msgp.WrapError(err, "Res")
				return
			}
		case "func":
			bts, err = z.Func.UnmarshalMsg(bts)
			if err != nil {
				err = msgp.WrapError(err, "Func")
				return
			}
		default:
			bts, err = msgp.Skip(bts)
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	o = bts
	return
}

// Msgsize returns an upper bound estimate of the number of bytes occupied by the serialized message
func (z *FnMsg) Msgsize() (s int) {
	s = 1 + 4 + msgp.UintSize + 4 + z.Res.Msgsize() + 5 + z.Func.Msgsize()
	return
}

// DecodeMsg implements msgp.Decodable
func (z *PossibleRes) DecodeMsg(dc *msgp.Reader) (err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, err = dc.ReadMapHeader()
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, err = dc.ReadMapKeyPtr()
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "Cores":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Cores")
					return
				}
				z.Cores = nil
			} else {
				if z.Cores == nil {
					z.Cores = new(struct {
						N []uint
					})
				}
				var zb0002 uint32
				zb0002, err = dc.ReadMapHeader()
				if err != nil {
					err = msgp.WrapError(err, "Cores")
					return
				}
				for zb0002 > 0 {
					zb0002--
					field, err = dc.ReadMapKeyPtr()
					if err != nil {
						err = msgp.WrapError(err, "Cores")
						return
					}
					switch msgp.UnsafeString(field) {
					case "N":
						var zb0003 uint32
						zb0003, err = dc.ReadArrayHeader()
						if err != nil {
							err = msgp.WrapError(err, "Cores", "N")
							return
						}
						if cap(z.Cores.N) >= int(zb0003) {
							z.Cores.N = (z.Cores.N)[:zb0003]
						} else {
							z.Cores.N = make([]uint, zb0003)
						}
						for za0001 := range z.Cores.N {
							z.Cores.N[za0001], err = dc.ReadUint()
							if err != nil {
								err = msgp.WrapError(err, "Cores", "N", za0001)
								return
							}
						}
					default:
						err = dc.Skip()
						if err != nil {
							err = msgp.WrapError(err, "Cores")
							return
						}
					}
				}
			}
		case "Memory":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Memory")
					return
				}
				z.Memory = nil
			} else {
				if z.Memory == nil {
					z.Memory = new(struct {
						M uint
					})
				}
				var zb0004 uint32
				zb0004, err = dc.ReadMapHeader()
				if err != nil {
					err = msgp.WrapError(err, "Memory")
					return
				}
				for zb0004 > 0 {
					zb0004--
					field, err = dc.ReadMapKeyPtr()
					if err != nil {
						err = msgp.WrapError(err, "Memory")
						return
					}
					switch msgp.UnsafeString(field) {
					case "M":
						z.Memory.M, err = dc.ReadUint()
						if err != nil {
							err = msgp.WrapError(err, "Memory", "M")
							return
						}
					default:
						err = dc.Skip()
						if err != nil {
							err = msgp.WrapError(err, "Memory")
							return
						}
					}
				}
			}
		case "WTime":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "WTime")
					return
				}
				z.WTime = nil
			} else {
				if z.WTime == nil {
					z.WTime = new(WTimeMsg)
				}
				err = z.WTime.DecodeMsg(dc)
				if err != nil {
					err = msgp.WrapError(err, "WTime")
					return
				}
			}
		case "Capacity":
			if dc.IsNil() {
				err = dc.ReadNil()
				if err != nil {
					err = msgp.WrapError(err, "Capacity")
					return
				}
				z.Capacity = nil
			} else {
				if z.Capacity == nil {
					z.Capacity = new(struct {
						V int
					})
				}
				var zb0005 uint32
				zb0005, err = dc.ReadMapHeader()
				if err != nil {
					err = msgp.WrapError(err, "Capacity")
					return
				}
				for zb0005 > 0 {
					zb0005--
					field, err = dc.ReadMapKeyPtr()
					if err != nil {
						err = msgp.WrapError(err, "Capacity")
						return
					}
					switch msgp.UnsafeString(field) {
					case "V":
						z.Capacity.V, err = dc.ReadInt()
						if err != nil {
							err = msgp.WrapError(err, "Capacity", "V")
							return
						}
					default:
						err = dc.Skip()
						if err != nil {
							err = msgp.WrapError(err, "Capacity")
							return
						}
					}
				}
			}
		default:
			err = dc.Skip()
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	return
}

// EncodeMsg implements msgp.Encodable
func (z *PossibleRes) EncodeMsg(en *msgp.Writer) (err error) {
	// omitempty: check for empty values
	zb0001Len := uint32(4)
	var zb0001Mask uint8 /* 4 bits */
	if z.Cores == nil {
		zb0001Len--
		zb0001Mask |= 0x1
	}
	if z.Memory == nil {
		zb0001Len--
		zb0001Mask |= 0x2
	}
	if z.WTime == nil {
		zb0001Len--
		zb0001Mask |= 0x4
	}
	if z.Capacity == nil {
		zb0001Len--
		zb0001Mask |= 0x8
	}
	// variable map header, size zb0001Len
	err = en.Append(0x80 | uint8(zb0001Len))
	if err != nil {
		return
	}
	if zb0001Len == 0 {
		return
	}
	if (zb0001Mask & 0x1) == 0 { // if not empty
		// write "Cores"
		err = en.Append(0xa5, 0x43, 0x6f, 0x72, 0x65, 0x73)
		if err != nil {
			return
		}
		if z.Cores == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			// map header, size 1
			// write "N"
			err = en.Append(0x81, 0xa1, 0x4e)
			if err != nil {
				return
			}
			err = en.WriteArrayHeader(uint32(len(z.Cores.N)))
			if err != nil {
				err = msgp.WrapError(err, "Cores", "N")
				return
			}
			for za0001 := range z.Cores.N {
				err = en.WriteUint(z.Cores.N[za0001])
				if err != nil {
					err = msgp.WrapError(err, "Cores", "N", za0001)
					return
				}
			}
		}
	}
	if (zb0001Mask & 0x2) == 0 { // if not empty
		// write "Memory"
		err = en.Append(0xa6, 0x4d, 0x65, 0x6d, 0x6f, 0x72, 0x79)
		if err != nil {
			return
		}
		if z.Memory == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			// map header, size 1
			// write "M"
			err = en.Append(0x81, 0xa1, 0x4d)
			if err != nil {
				return
			}
			err = en.WriteUint(z.Memory.M)
			if err != nil {
				err = msgp.WrapError(err, "Memory", "M")
				return
			}
		}
	}
	if (zb0001Mask & 0x4) == 0 { // if not empty
		// write "WTime"
		err = en.Append(0xa5, 0x57, 0x54, 0x69, 0x6d, 0x65)
		if err != nil {
			return
		}
		if z.WTime == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			err = z.WTime.EncodeMsg(en)
			if err != nil {
				err = msgp.WrapError(err, "WTime")
				return
			}
		}
	}
	if (zb0001Mask & 0x8) == 0 { // if not empty
		// write "Capacity"
		err = en.Append(0xa8, 0x43, 0x61, 0x70, 0x61, 0x63, 0x69, 0x74, 0x79)
		if err != nil {
			return
		}
		if z.Capacity == nil {
			err = en.WriteNil()
			if err != nil {
				return
			}
		} else {
			// map header, size 1
			// write "V"
			err = en.Append(0x81, 0xa1, 0x56)
			if err != nil {
				return
			}
			err = en.WriteInt(z.Capacity.V)
			if err != nil {
				err = msgp.WrapError(err, "Capacity", "V")
				return
			}
		}
	}
	return
}

// MarshalMsg implements msgp.Marshaler
func (z *PossibleRes) MarshalMsg(b []byte) (o []byte, err error) {
	o = msgp.Require(b, z.Msgsize())
	// omitempty: check for empty values
	zb0001Len := uint32(4)
	var zb0001Mask uint8 /* 4 bits */
	if z.Cores == nil {
		zb0001Len--
		zb0001Mask |= 0x1
	}
	if z.Memory == nil {
		zb0001Len--
		zb0001Mask |= 0x2
	}
	if z.WTime == nil {
		zb0001Len--
		zb0001Mask |= 0x4
	}
	if z.Capacity == nil {
		zb0001Len--
		zb0001Mask |= 0x8
	}
	// variable map header, size zb0001Len
	o = append(o, 0x80|uint8(zb0001Len))
	if zb0001Len == 0 {
		return
	}
	if (zb0001Mask & 0x1) == 0 { // if not empty
		// string "Cores"
		o = append(o, 0xa5, 0x43, 0x6f, 0x72, 0x65, 0x73)
		if z.Cores == nil {
			o = msgp.AppendNil(o)
		} else {
			// map header, size 1
			// string "N"
			o = append(o, 0x81, 0xa1, 0x4e)
			o = msgp.AppendArrayHeader(o, uint32(len(z.Cores.N)))
			for za0001 := range z.Cores.N {
				o = msgp.AppendUint(o, z.Cores.N[za0001])
			}
		}
	}
	if (zb0001Mask & 0x2) == 0 { // if not empty
		// string "Memory"
		o = append(o, 0xa6, 0x4d, 0x65, 0x6d, 0x6f, 0x72, 0x79)
		if z.Memory == nil {
			o = msgp.AppendNil(o)
		} else {
			// map header, size 1
			// string "M"
			o = append(o, 0x81, 0xa1, 0x4d)
			o = msgp.AppendUint(o, z.Memory.M)
		}
	}
	if (zb0001Mask & 0x4) == 0 { // if not empty
		// string "WTime"
		o = append(o, 0xa5, 0x57, 0x54, 0x69, 0x6d, 0x65)
		if z.WTime == nil {
			o = msgp.AppendNil(o)
		} else {
			o, err = z.WTime.MarshalMsg(o)
			if err != nil {
				err = msgp.WrapError(err, "WTime")
				return
			}
		}
	}
	if (zb0001Mask & 0x8) == 0 { // if not empty
		// string "Capacity"
		o = append(o, 0xa8, 0x43, 0x61, 0x70, 0x61, 0x63, 0x69, 0x74, 0x79)
		if z.Capacity == nil {
			o = msgp.AppendNil(o)
		} else {
			// map header, size 1
			// string "V"
			o = append(o, 0x81, 0xa1, 0x56)
			o = msgp.AppendInt(o, z.Capacity.V)
		}
	}
	return
}

// UnmarshalMsg implements msgp.Unmarshaler
func (z *PossibleRes) UnmarshalMsg(bts []byte) (o []byte, err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, bts, err = msgp.ReadMapHeaderBytes(bts)
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, bts, err = msgp.ReadMapKeyZC(bts)
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "Cores":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Cores = nil
			} else {
				if z.Cores == nil {
					z.Cores = new(struct {
						N []uint
					})
				}
				var zb0002 uint32
				zb0002, bts, err = msgp.ReadMapHeaderBytes(bts)
				if err != nil {
					err = msgp.WrapError(err, "Cores")
					return
				}
				for zb0002 > 0 {
					zb0002--
					field, bts, err = msgp.ReadMapKeyZC(bts)
					if err != nil {
						err = msgp.WrapError(err, "Cores")
						return
					}
					switch msgp.UnsafeString(field) {
					case "N":
						var zb0003 uint32
						zb0003, bts, err = msgp.ReadArrayHeaderBytes(bts)
						if err != nil {
							err = msgp.WrapError(err, "Cores", "N")
							return
						}
						if cap(z.Cores.N) >= int(zb0003) {
							z.Cores.N = (z.Cores.N)[:zb0003]
						} else {
							z.Cores.N = make([]uint, zb0003)
						}
						for za0001 := range z.Cores.N {
							z.Cores.N[za0001], bts, err = msgp.ReadUintBytes(bts)
							if err != nil {
								err = msgp.WrapError(err, "Cores", "N", za0001)
								return
							}
						}
					default:
						bts, err = msgp.Skip(bts)
						if err != nil {
							err = msgp.WrapError(err, "Cores")
							return
						}
					}
				}
			}
		case "Memory":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Memory = nil
			} else {
				if z.Memory == nil {
					z.Memory = new(struct {
						M uint
					})
				}
				var zb0004 uint32
				zb0004, bts, err = msgp.ReadMapHeaderBytes(bts)
				if err != nil {
					err = msgp.WrapError(err, "Memory")
					return
				}
				for zb0004 > 0 {
					zb0004--
					field, bts, err = msgp.ReadMapKeyZC(bts)
					if err != nil {
						err = msgp.WrapError(err, "Memory")
						return
					}
					switch msgp.UnsafeString(field) {
					case "M":
						z.Memory.M, bts, err = msgp.ReadUintBytes(bts)
						if err != nil {
							err = msgp.WrapError(err, "Memory", "M")
							return
						}
					default:
						bts, err = msgp.Skip(bts)
						if err != nil {
							err = msgp.WrapError(err, "Memory")
							return
						}
					}
				}
			}
		case "WTime":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.WTime = nil
			} else {
				if z.WTime == nil {
					z.WTime = new(WTimeMsg)
				}
				bts, err = z.WTime.UnmarshalMsg(bts)
				if err != nil {
					err = msgp.WrapError(err, "WTime")
					return
				}
			}
		case "Capacity":
			if msgp.IsNil(bts) {
				bts, err = msgp.ReadNilBytes(bts)
				if err != nil {
					return
				}
				z.Capacity = nil
			} else {
				if z.Capacity == nil {
					z.Capacity = new(struct {
						V int
					})
				}
				var zb0005 uint32
				zb0005, bts, err = msgp.ReadMapHeaderBytes(bts)
				if err != nil {
					err = msgp.WrapError(err, "Capacity")
					return
				}
				for zb0005 > 0 {
					zb0005--
					field, bts, err = msgp.ReadMapKeyZC(bts)
					if err != nil {
						err = msgp.WrapError(err, "Capacity")
						return
					}
					switch msgp.UnsafeString(field) {
					case "V":
						z.Capacity.V, bts, err = msgp.ReadIntBytes(bts)
						if err != nil {
							err = msgp.WrapError(err, "Capacity", "V")
							return
						}
					default:
						bts, err = msgp.Skip(bts)
						if err != nil {
							err = msgp.WrapError(err, "Capacity")
							return
						}
					}
				}
			}
		default:
			bts, err = msgp.Skip(bts)
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	o = bts
	return
}

// Msgsize returns an upper bound estimate of the number of bytes occupied by the serialized message
func (z *PossibleRes) Msgsize() (s int) {
	s = 1 + 6
	if z.Cores == nil {
		s += msgp.NilSize
	} else {
		s += 1 + 2 + msgp.ArrayHeaderSize + (len(z.Cores.N) * (msgp.UintSize))
	}
	s += 7
	if z.Memory == nil {
		s += msgp.NilSize
	} else {
		s += 1 + 2 + msgp.UintSize
	}
	s += 6
	if z.WTime == nil {
		s += msgp.NilSize
	} else {
		s += z.WTime.Msgsize()
	}
	s += 9
	if z.Capacity == nil {
		s += msgp.NilSize
	} else {
		s += 1 + 2 + msgp.IntSize
	}
	return
}

// DecodeMsg implements msgp.Decodable
func (z *ResultMsg) DecodeMsg(dc *msgp.Reader) (err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, err = dc.ReadMapHeader()
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, err = dc.ReadMapKeyPtr()
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "tid":
			z.Tid, err = dc.ReadUint()
			if err != nil {
				err = msgp.WrapError(err, "Tid")
				return
			}
		case "exception":
			z.Exception, err = dc.ReadString()
			if err != nil {
				err = msgp.WrapError(err, "Exception")
				return
			}
		case "result":
			err = z.Result.DecodeMsg(dc)
			if err != nil {
				err = msgp.WrapError(err, "Result")
				return
			}
		default:
			err = dc.Skip()
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	return
}

// EncodeMsg implements msgp.Encodable
func (z *ResultMsg) EncodeMsg(en *msgp.Writer) (err error) {
	// map header, size 3
	// write "tid"
	err = en.Append(0x83, 0xa3, 0x74, 0x69, 0x64)
	if err != nil {
		return
	}
	err = en.WriteUint(z.Tid)
	if err != nil {
		err = msgp.WrapError(err, "Tid")
		return
	}
	// write "exception"
	err = en.Append(0xa9, 0x65, 0x78, 0x63, 0x65, 0x70, 0x74, 0x69, 0x6f, 0x6e)
	if err != nil {
		return
	}
	err = en.WriteString(z.Exception)
	if err != nil {
		err = msgp.WrapError(err, "Exception")
		return
	}
	// write "result"
	err = en.Append(0xa6, 0x72, 0x65, 0x73, 0x75, 0x6c, 0x74)
	if err != nil {
		return
	}
	err = z.Result.EncodeMsg(en)
	if err != nil {
		err = msgp.WrapError(err, "Result")
		return
	}
	return
}

// MarshalMsg implements msgp.Marshaler
func (z *ResultMsg) MarshalMsg(b []byte) (o []byte, err error) {
	o = msgp.Require(b, z.Msgsize())
	// map header, size 3
	// string "tid"
	o = append(o, 0x83, 0xa3, 0x74, 0x69, 0x64)
	o = msgp.AppendUint(o, z.Tid)
	// string "exception"
	o = append(o, 0xa9, 0x65, 0x78, 0x63, 0x65, 0x70, 0x74, 0x69, 0x6f, 0x6e)
	o = msgp.AppendString(o, z.Exception)
	// string "result"
	o = append(o, 0xa6, 0x72, 0x65, 0x73, 0x75, 0x6c, 0x74)
	o, err = z.Result.MarshalMsg(o)
	if err != nil {
		err = msgp.WrapError(err, "Result")
		return
	}
	return
}

// UnmarshalMsg implements msgp.Unmarshaler
func (z *ResultMsg) UnmarshalMsg(bts []byte) (o []byte, err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, bts, err = msgp.ReadMapHeaderBytes(bts)
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, bts, err = msgp.ReadMapKeyZC(bts)
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "tid":
			z.Tid, bts, err = msgp.ReadUintBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Tid")
				return
			}
		case "exception":
			z.Exception, bts, err = msgp.ReadStringBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Exception")
				return
			}
		case "result":
			bts, err = z.Result.UnmarshalMsg(bts)
			if err != nil {
				err = msgp.WrapError(err, "Result")
				return
			}
		default:
			bts, err = msgp.Skip(bts)
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	o = bts
	return
}

// Msgsize returns an upper bound estimate of the number of bytes occupied by the serialized message
func (z *ResultMsg) Msgsize() (s int) {
	s = 1 + 4 + msgp.UintSize + 10 + msgp.StringPrefixSize + len(z.Exception) + 7 + z.Result.Msgsize()
	return
}

// DecodeMsg implements msgp.Decodable
func (z *WTimeMsg) DecodeMsg(dc *msgp.Reader) (err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, err = dc.ReadMapHeader()
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, err = dc.ReadMapKeyPtr()
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "T":
			z.T, err = dc.ReadUint64()
			if err != nil {
				err = msgp.WrapError(err, "T")
				return
			}
		case "softT":
			z.SoftT, err = dc.ReadUint64()
			if err != nil {
				err = msgp.WrapError(err, "SoftT")
				return
			}
		case "group":
			z.Group, err = dc.ReadString()
			if err != nil {
				err = msgp.WrapError(err, "Group")
				return
			}
		case "countdown":
			z.Countdown, err = dc.ReadBool()
			if err != nil {
				err = msgp.WrapError(err, "Countdown")
				return
			}
		default:
			err = dc.Skip()
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	return
}

// EncodeMsg implements msgp.Encodable
func (z *WTimeMsg) EncodeMsg(en *msgp.Writer) (err error) {
	// map header, size 4
	// write "T"
	err = en.Append(0x84, 0xa1, 0x54)
	if err != nil {
		return
	}
	err = en.WriteUint64(z.T)
	if err != nil {
		err = msgp.WrapError(err, "T")
		return
	}
	// write "softT"
	err = en.Append(0xa5, 0x73, 0x6f, 0x66, 0x74, 0x54)
	if err != nil {
		return
	}
	err = en.WriteUint64(z.SoftT)
	if err != nil {
		err = msgp.WrapError(err, "SoftT")
		return
	}
	// write "group"
	err = en.Append(0xa5, 0x67, 0x72, 0x6f, 0x75, 0x70)
	if err != nil {
		return
	}
	err = en.WriteString(z.Group)
	if err != nil {
		err = msgp.WrapError(err, "Group")
		return
	}
	// write "countdown"
	err = en.Append(0xa9, 0x63, 0x6f, 0x75, 0x6e, 0x74, 0x64, 0x6f, 0x77, 0x6e)
	if err != nil {
		return
	}
	err = en.WriteBool(z.Countdown)
	if err != nil {
		err = msgp.WrapError(err, "Countdown")
		return
	}
	return
}

// MarshalMsg implements msgp.Marshaler
func (z *WTimeMsg) MarshalMsg(b []byte) (o []byte, err error) {
	o = msgp.Require(b, z.Msgsize())
	// map header, size 4
	// string "T"
	o = append(o, 0x84, 0xa1, 0x54)
	o = msgp.AppendUint64(o, z.T)
	// string "softT"
	o = append(o, 0xa5, 0x73, 0x6f, 0x66, 0x74, 0x54)
	o = msgp.AppendUint64(o, z.SoftT)
	// string "group"
	o = append(o, 0xa5, 0x67, 0x72, 0x6f, 0x75, 0x70)
	o = msgp.AppendString(o, z.Group)
	// string "countdown"
	o = append(o, 0xa9, 0x63, 0x6f, 0x75, 0x6e, 0x74, 0x64, 0x6f, 0x77, 0x6e)
	o = msgp.AppendBool(o, z.Countdown)
	return
}

// UnmarshalMsg implements msgp.Unmarshaler
func (z *WTimeMsg) UnmarshalMsg(bts []byte) (o []byte, err error) {
	var field []byte
	_ = field
	var zb0001 uint32
	zb0001, bts, err = msgp.ReadMapHeaderBytes(bts)
	if err != nil {
		err = msgp.WrapError(err)
		return
	}
	for zb0001 > 0 {
		zb0001--
		field, bts, err = msgp.ReadMapKeyZC(bts)
		if err != nil {
			err = msgp.WrapError(err)
			return
		}
		switch msgp.UnsafeString(field) {
		case "T":
			z.T, bts, err = msgp.ReadUint64Bytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "T")
				return
			}
		case "softT":
			z.SoftT, bts, err = msgp.ReadUint64Bytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "SoftT")
				return
			}
		case "group":
			z.Group, bts, err = msgp.ReadStringBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Group")
				return
			}
		case "countdown":
			z.Countdown, bts, err = msgp.ReadBoolBytes(bts)
			if err != nil {
				err = msgp.WrapError(err, "Countdown")
				return
			}
		default:
			bts, err = msgp.Skip(bts)
			if err != nil {
				err = msgp.WrapError(err)
				return
			}
		}
	}
	o = bts
	return
}

// Msgsize returns an upper bound estimate of the number of bytes occupied by the serialized message
func (z *WTimeMsg) Msgsize() (s int) {
	s = 1 + 2 + msgp.Uint64Size + 6 + msgp.Uint64Size + 6 + msgp.StringPrefixSize + len(z.Group) + 10 + msgp.BoolSize
	return
}
