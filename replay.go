package main

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
)

var header = []byte("{U\x03raw[$U#l")

// ubjson is a minimal UBJSON decoder (just what Slippi metadata uses).
// Returns the value and the index just past it.
func ubjson(buf []byte, i int) (any, int, error) {
	need := func(n int) error {
		if i+n > len(buf) {
			return fmt.Errorf("truncated UBJSON at %d", i)
		}
		return nil
	}
	if err := need(1); err != nil {
		return nil, i, err
	}
	t := buf[i]
	i++
	sizes := map[byte]int{'i': 1, 'U': 1, 'I': 2, 'l': 4, 'L': 8, 'd': 4, 'D': 8}
	if n, ok := sizes[t]; ok {
		if err := need(n); err != nil {
			return nil, i, err
		}
		b := buf[i : i+n]
		var v any
		switch t {
		case 'i':
			v = int(int8(b[0]))
		case 'U':
			v = int(b[0])
		case 'I':
			v = int(int16(binary.BigEndian.Uint16(b)))
		case 'l':
			v = int(int32(binary.BigEndian.Uint32(b)))
		case 'L':
			v = int(int64(binary.BigEndian.Uint64(b)))
		case 'd':
			v = float64(math.Float32frombits(binary.BigEndian.Uint32(b)))
		case 'D':
			v = math.Float64frombits(binary.BigEndian.Uint64(b))
		}
		return v, i + n, nil
	}
	switch t {
	case 'S':
		s, next, err := ubjsonBytes(buf, i)
		return string(s), next, err
	case 'T':
		return true, i, nil
	case 'F':
		return false, i, nil
	case 'Z':
		return nil, i, nil
	case '{':
		d := map[string]any{}
		for {
			if err := need(1); err != nil {
				return nil, i, err
			}
			if buf[i] == '}' {
				return d, i + 1, nil
			}
			key, next, err := ubjsonBytes(buf, i) // keys are a length int + bytes, no 'S'
			if err != nil {
				return nil, next, err
			}
			v, next, err := ubjson(buf, next)
			if err != nil {
				return nil, next, err
			}
			d[string(key)] = v
			i = next
		}
	case '[':
		var a []any
		for {
			if err := need(1); err != nil {
				return nil, i, err
			}
			if buf[i] == ']' {
				return a, i + 1, nil
			}
			v, next, err := ubjson(buf, i)
			if err != nil {
				return nil, next, err
			}
			a = append(a, v)
			i = next
		}
	}
	return nil, i, fmt.Errorf("unsupported UBJSON type %q at %d", t, i-1)
}

func ubjsonBytes(buf []byte, i int) ([]byte, int, error) {
	v, i, err := ubjson(buf, i)
	if err != nil {
		return nil, i, err
	}
	n, ok := v.(int)
	if !ok || n < 0 || i+n > len(buf) {
		return nil, i, fmt.Errorf("bad UBJSON length at %d", i)
	}
	return buf[i : i+n], i + n, nil
}

// rawLength is 0 while the game is still being written; Slippi fills it in when the game ends.
func rawLength(path string) uint32 {
	f, err := os.Open(path)
	if err != nil {
		return 0
	}
	defer f.Close()
	head := make([]byte, 15)
	if _, err := io.ReadFull(f, head); err != nil || !bytes.HasPrefix(head, header) {
		return 0
	}
	return binary.BigEndian.Uint32(head[11:15])
}

// payloadSizes reads the Event Payloads event at the start of the raw stream.
// Returns the size of each command and where the next event starts.
func payloadSizes(raw []byte) (map[byte]int, int) {
	if len(raw) < 2 || raw[0] != 0x35 {
		return nil, 0
	}
	blen := int(raw[1])
	sizes := map[byte]int{}
	for j := 2; j+2 < len(raw) && j < 1+blen; j += 3 {
		sizes[raw[j]] = int(binary.BigEndian.Uint16(raw[j+1 : j+3]))
	}
	return sizes, 1 + blen
}

// Game is the outcome of a finished replay. Winner and Quitter are -1 when there is none.
type Game struct {
	Codes   map[int]string
	Winner  int
	Quitter int
}

func parseGame(path string) (Game, error) {
	g := Game{Codes: map[int]string{}, Winner: -1, Quitter: -1}
	data, err := os.ReadFile(path)
	if err != nil {
		return g, err
	}
	if len(data) < 15 || !bytes.HasPrefix(data, header) {
		return g, errors.New("not a Slippi replay")
	}
	n := int(binary.BigEndian.Uint32(data[11:15]))
	if 15+n > len(data) {
		return g, errors.New("replay is truncated")
	}
	raw := data[15 : 15+n]

	// metadata -> connect codes per port
	meta, _, err := ubjson(data, 15+n+len("U\x08metadata"))
	if err != nil {
		return g, fmt.Errorf("reading metadata: %w", err)
	}
	if m, ok := meta.(map[string]any); ok {
		players, _ := m["players"].(map[string]any)
		for p, v := range players {
			port, err := strconv.Atoi(p)
			if err != nil {
				continue
			}
			pm, _ := v.(map[string]any)
			names, _ := pm["names"].(map[string]any)
			code, _ := names["code"].(string)
			g.Codes[port] = code
		}
	}

	// event stream -> stocks and game-end info
	sizes, pos := payloadSizes(raw)
	stocks, percent := map[int]int{}, map[int]float32{}
	var ports []int // in first-seen order
	var end []byte
	for pos < len(raw) {
		cmd := raw[pos]
		size, ok := sizes[cmd]
		if !ok || pos+1+size > len(raw) {
			break
		}
		ev := raw[pos : pos+1+size]
		if cmd == 0x38 && len(ev) > 0x21 && ev[6] == 0 { // post-frame, non-follower (ignore Nana)
			port := int(ev[5])
			if _, seen := stocks[port]; !seen {
				ports = append(ports, port)
			}
			percent[port] = math.Float32frombits(binary.BigEndian.Uint32(ev[0x16:0x1A]))
			stocks[port] = int(ev[0x21])
		} else if cmd == 0x39 {
			end = ev[1:]
		}
		pos += 1 + size
	}

	if end == nil || len(ports) != 2 {
		return g, nil // crashed/doubles/etc.
	}
	if len(end) >= 2 {
		g.Quitter = int(int8(end[1]))
	}
	if g.Quitter != -1 {
		return g, nil // someone quit (LRAS): no winner
	}
	if len(end) >= 6 { // newer replays store placements directly
		for _, port := range ports {
			if port < 4 && int8(end[2+port]) == 0 {
				g.Winner = port
				return g, nil
			}
		}
	}
	a, b := ports[0], ports[1]
	switch {
	case stocks[a] != stocks[b]:
		g.Winner = pick(stocks[a] > stocks[b], a, b)
	case percent[a] != percent[b]: // timeout with equal stocks
		g.Winner = pick(percent[a] < percent[b], a, b)
	}
	return g, nil
}

func pick(cond bool, a, b int) int {
	if cond {
		return a
	}
	return b
}

// startCodes returns connect codes by port from the Game Start event, which Slippi
// writes as soon as the game begins. Returns nil if it isn't on disk yet.
func startCodes(path string) map[int]string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	head := make([]byte, 2048)
	n, _ := io.ReadFull(f, head)
	if n < 15 {
		return nil
	}
	raw := head[15:n]
	sizes, pos := payloadSizes(raw)
	if sizes == nil || pos >= len(raw) {
		return nil
	}
	gs := raw[pos:min(len(raw), pos+1+sizes[0x36])]
	if len(gs) < 0x221+0xA*4 || gs[0] != 0x36 {
		return nil
	}
	codes := map[int]string{}
	for port := 0; port < 4; port++ {
		field := gs[0x221+0xA*port : 0x22B+0xA*port]
		if i := bytes.IndexByte(field, 0); i >= 0 {
			field = field[:i]
		}
		if len(field) > 0 {
			codes[port] = decodeCode(field)
		}
	}
	return codes
}

// decodeCode decodes a Shift-JIS connect code. Codes are ASCII apart from the
// fullwidth '#' (0x81 0x94), so that's all this handles.
func decodeCode(b []byte) string {
	out := make([]byte, 0, len(b))
	for i := 0; i < len(b); i++ {
		switch {
		case b[i] == 0x81 && i+1 < len(b) && b[i+1] == 0x94:
			out = append(out, '#')
			i++
		case b[i] < 0x80:
			out = append(out, b[i])
		default:
			out = append(out, '?')
		}
	}
	return string(out)
}
