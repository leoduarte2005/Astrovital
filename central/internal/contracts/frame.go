package contracts

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
)

// MaxFrameBytes is the IPC frame body limit (1 MiB). len==0 or len>Max is a protocol error.
const MaxFrameBytes = 1 << 20

// ErrFrameSize marks an invalid IPC frame length (0 or > MaxFrameBytes).
var ErrFrameSize = errors.New("contracts: invalid frame size")

// FrameReader reads uint32 big-endian length-prefixed frames using a reusable buffer.
// The slice returned by Read is valid only until the next call to Read.
type FrameReader struct {
	hdr [4]byte
	buf []byte
}

// Read reads one frame using io.ReadFull for header and body.
func (f *FrameReader) Read(r io.Reader) ([]byte, error) {
	if _, err := io.ReadFull(r, f.hdr[:]); err != nil {
		return nil, err
	}
	n := binary.BigEndian.Uint32(f.hdr[:])
	if n == 0 || n > MaxFrameBytes {
		return nil, fmt.Errorf("%w: %d", ErrFrameSize, n)
	}
	if cap(f.buf) < int(n) {
		f.buf = make([]byte, n)
	}
	body := f.buf[:n]
	if _, err := io.ReadFull(r, body); err != nil {
		if errors.Is(err, io.EOF) {
			err = io.ErrUnexpectedEOF
		}
		return nil, err
	}
	return body, nil
}

// FrameWriter writes header+body with a single Write call, reusing its scratch buffer.
type FrameWriter struct {
	buf []byte
}

// Write emits one frame to w.
func (f *FrameWriter) Write(w io.Writer, body []byte) error {
	n := len(body)
	if n == 0 || n > MaxFrameBytes {
		return fmt.Errorf("%w: %d", ErrFrameSize, n)
	}
	f.buf = append(f.buf[:0], 0, 0, 0, 0)
	binary.BigEndian.PutUint32(f.buf, uint32(n))
	f.buf = append(f.buf, body...)
	_, err := w.Write(f.buf)
	return err
}
