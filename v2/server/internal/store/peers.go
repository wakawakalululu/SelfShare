package store

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// PeerTTL 与 Python 端一致：超过即视为离线，从发现结果中剔除。
const PeerTTL = 300.0

const (
	peersFileName    = "peers.json"
	blobsDiscoverMax = 20000
	registerBlobMax  = 50000
)

type Peer struct {
	PeerID    string   `json:"peer_id"`
	Listen    string   `json:"listen"`
	Blobs     []string `json:"blobs"`
	BlobCount int      `json:"blob_count"`
	Vault     string   `json:"vault"`
	LastSeen  float64  `json:"last_seen"`
	HostID    string   `json:"host_id"`
	Version   string   `json:"version"`
}

type peersFile struct {
	Peers []*Peer `json:"peers"`
}

// PeerRegistry 保存各节点上报的监听地址与持有的 blob 摘要。
type PeerRegistry struct {
	path string
	mu   sync.Mutex
}

func NewPeerRegistry(vaultRoot string) *PeerRegistry {
	return &PeerRegistry{path: filepath.Join(vaultRoot, peersFileName)}
}

func (r *PeerRegistry) load() (*peersFile, error) {
	raw, err := os.ReadFile(r.path)
	if os.IsNotExist(err) {
		return &peersFile{}, nil
	}
	if err != nil {
		return nil, err
	}
	var f peersFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, err
	}
	return &f, nil
}

func (r *PeerRegistry) save(f *peersFile) error {
	payload, err := marshalSorted(f)
	if err != nil {
		return err
	}
	return AtomicWrite(r.path, payload)
}

func nowFloat() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// Register 覆盖同名节点的旧记录。
func (r *PeerRegistry) Register(vaultID, peerID, listen string, blobs []string, hostID, version string) map[string]any {
	r.mu.Lock()
	defer r.mu.Unlock()
	f, err := r.load()
	if err != nil {
		f = &peersFile{}
	}
	kept := f.Peers[:0]
	for _, p := range f.Peers {
		if p.PeerID == peerID && p.Vault == vaultID {
			continue
		}
		kept = append(kept, p)
	}
	blobCount := len(blobs)
	if len(blobs) > registerBlobMax {
		blobs = blobs[:registerBlobMax]
	}
	if blobs == nil {
		blobs = []string{}
	}
	f.Peers = append(kept, &Peer{
		PeerID: peerID, Listen: listen, Blobs: blobs, BlobCount: blobCount,
		Vault: vaultID, LastSeen: nowFloat(), HostID: hostID, Version: version,
	})
	_ = r.save(f)
	return map[string]any{
		"peer_id": peerID, "vault": vaultID, "registered": true, "ttl": PeerTTL,
	}
}

// Heartbeat 刷新存活时间；blobs 为 nil 时沿用旧列表（兼容只上报计数的老客户端）。
func (r *PeerRegistry) Heartbeat(vaultID, peerID string, blobCount int, blobs []string) map[string]any {
	r.mu.Lock()
	defer r.mu.Unlock()
	f, err := r.load()
	if err != nil {
		return map[string]any{"ok": false, "error": "peer not registered"}
	}
	found := false
	for _, p := range f.Peers {
		if p.PeerID == peerID && p.Vault == vaultID {
			p.LastSeen = nowFloat()
			p.BlobCount = blobCount
			if blobs != nil {
				if len(blobs) > registerBlobMax {
					blobs = blobs[:registerBlobMax]
				}
				p.Blobs = blobs
			}
			found = true
		}
	}
	if !found {
		return map[string]any{"ok": false, "error": "peer not registered"}
	}
	_ = r.save(f)
	return map[string]any{"ok": true, "ttl": PeerTTL}
}

func (r *PeerRegistry) Unregister(vaultID, peerID string) map[string]any {
	r.mu.Lock()
	defer r.mu.Unlock()
	f, err := r.load()
	if err != nil {
		return map[string]any{"ok": true}
	}
	kept := f.Peers[:0]
	for _, p := range f.Peers {
		if p.PeerID == peerID && p.Vault == vaultID {
			continue
		}
		kept = append(kept, p)
	}
	f.Peers = kept
	_ = r.save(f)
	return map[string]any{"ok": true}
}

// Discover 返回在线节点；withBlobs 为真时才附带摘要列表，保持默认响应精简。
func (r *PeerRegistry) Discover(vaultID, exclude string, withBlobs bool) []map[string]any {
	r.mu.Lock()
	defer r.mu.Unlock()
	f, err := r.load()
	if err != nil {
		return nil
	}
	now := nowFloat()
	out := make([]map[string]any, 0, len(f.Peers))
	for _, p := range f.Peers {
		if p.Vault != vaultID {
			continue
		}
		if now-p.LastSeen > PeerTTL {
			continue
		}
		if exclude != "" && p.PeerID == exclude {
			continue
		}
		entry := map[string]any{
			"peer_id": p.PeerID, "listen": p.Listen, "blob_count": p.BlobCount,
			"host_id": p.HostID, "version": p.Version, "last_seen": p.LastSeen,
		}
		if withBlobs {
			blobs := p.Blobs
			if len(blobs) > blobsDiscoverMax {
				blobs = blobs[:blobsDiscoverMax]
			}
			if blobs == nil {
				blobs = []string{}
			}
			entry["blobs"] = blobs
		}
		out = append(out, entry)
	}
	// 与 Python 一致：按 last_seen 倒序
	for i := 1; i < len(out); i++ {
		for j := i; j > 0; j-- {
			a, _ := out[j]["last_seen"].(float64)
			b, _ := out[j-1]["last_seen"].(float64)
			if a <= b {
				break
			}
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
