// Package cluster manages ESP32-S3 node discovery, MAC->node_id registry,
// per-node liveness FSM, TDM SlotMap recalculation, and N+1 failover.
// This package only imports stdlib and internal/contracts.
package cluster

import (
	"sort"

	"edgespace/central/internal/contracts"
)

const (
	// MaxNodes is the fixed maximum number of ESP32-S3 nodes in the cluster (IDs 0..4).
	MaxNodes = 5
	// MaxLinks is the maximum number of directed (tx != rx) CSI links (5 * 4 = 20).
	MaxLinks = MaxNodes * (MaxNodes - 1)
)

// Peripheral bitmap bits tracked per node.
const (
	PeriphBitMAX30102 uint8 = 1 << 0
	PeriphBitBME280   uint8 = 1 << 1
	PeriphBitSCD40    uint8 = 1 << 2
)

// SlotMap holds the immutable TDM slot schedule and active link masks shared atomically.
type SlotMap struct {
	Version        uint64
	ActiveNodes    int
	ActiveLinks    int
	SlotMs         int
	ActiveNodeMask uint8
	ActiveLinkMask uint32
	Slots          []contracts.SlotAssignment
	// NodeSlot maps node_id (0..4) -> assigned slot_id, or -1 if inactive.
	NodeSlot [MaxNodes]int
}

// LinkBitIndex returns the canonical 0..19 bit index in ActiveLinkMask for pair (tx, rx) with tx != rx.
func LinkBitIndex(tx, rx uint8) (int, bool) {
	if tx >= MaxNodes || rx >= MaxNodes || tx == rx {
		return -1, false
	}
	if rx < tx {
		return int(tx)*(MaxNodes-1) + int(rx), true
	}
	return int(tx)*(MaxNodes-1) + int(rx-1), true
}

// BuildSlotMap constructs an immutable SlotMap from the active node bitmask (bits 0..4).
func BuildSlotMap(version uint64, activeNodeMask uint8) *SlotMap {
	sm := &SlotMap{
		Version:        version,
		ActiveNodeMask: activeNodeMask & ((1 << MaxNodes) - 1),
	}
	for i := range sm.NodeSlot {
		sm.NodeSlot[i] = -1
	}

	var activeIDs []uint8
	for id := uint8(0); id < MaxNodes; id++ {
		if sm.ActiveNodeMask&(1<<id) != 0 {
			activeIDs = append(activeIDs, id)
		}
	}
	sort.Slice(activeIDs, func(i, j int) bool { return activeIDs[i] < activeIDs[j] })

	k := len(activeIDs)
	sm.ActiveNodes = k
	if k > 0 {
		sm.SlotMs = 100 / k
		sm.Slots = make([]contracts.SlotAssignment, k)
		for slotIdx, nodeID := range activeIDs {
			sm.Slots[slotIdx] = contracts.SlotAssignment{
				NodeID: nodeID,
				SlotID: uint8(slotIdx),
				Ms:     sm.SlotMs,
			}
			sm.NodeSlot[nodeID] = slotIdx
		}
	}

	for _, tx := range activeIDs {
		for _, rx := range activeIDs {
			if tx == rx {
				continue
			}
			if bit, ok := LinkBitIndex(tx, rx); ok {
				sm.ActiveLinkMask |= 1 << uint(bit)
				sm.ActiveLinks++
			}
		}
	}

	return sm
}

// PeripheralBit returns the bitmap bit for a valid Peripheral.
func PeripheralBit(p contracts.Peripheral) uint8 {
	switch p {
	case contracts.PeripheralMAX30102:
		return PeriphBitMAX30102
	case contracts.PeripheralBME280:
		return PeriphBitBME280
	case contracts.PeripheralSCD40:
		return PeriphBitSCD40
	default:
		return 0
	}
}

// PeripheralsToMask converts a slice of Peripheral enums into a bitmap.
func PeripheralsToMask(list []contracts.Peripheral) uint8 {
	var mask uint8
	for _, p := range list {
		mask |= PeripheralBit(p)
	}
	return mask
}

// MaskToPeripherals converts a peripheral bitmap into a canonical sorted slice.
func MaskToPeripherals(mask uint8) []contracts.Peripheral {
	var out []contracts.Peripheral
	if mask&PeriphBitMAX30102 != 0 {
		out = append(out, contracts.PeripheralMAX30102)
	}
	if mask&PeriphBitBME280 != 0 {
		out = append(out, contracts.PeripheralBME280)
	}
	if mask&PeriphBitSCD40 != 0 {
		out = append(out, contracts.PeripheralSCD40)
	}
	return out
}
