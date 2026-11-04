package store

import "testing"

func TestPeerRegisterDiscover(t *testing.T) {
	r := NewPeerRegistry(t.TempDir())
	r.Register("default", "p1", "127.0.0.1:9001", []string{"digest-a"}, "host-a", "2.0.0")
	r.Register("default", "p2", "127.0.0.1:9002", []string{"digest-b"}, "host-b", "2.0.0")

	peers := r.Discover("default", "", false)
	if len(peers) != 2 {
		t.Fatalf("Discover = %d peers, want 2", len(peers))
	}
	if _, ok := peers[0]["blobs"]; ok {
		t.Fatal("精简响应不应携带 blobs 列表")
	}
	withBlobs := r.Discover("default", "", true)
	if _, ok := withBlobs[0]["blobs"]; !ok {
		t.Fatal("withBlobs=true 时应携带 blobs 列表")
	}
	if got := r.Discover("other-vault", "", false); len(got) != 0 {
		t.Fatalf("跨库泄漏了 %d 个节点", len(got))
	}
}

func TestPeerHeartbeatUnregister(t *testing.T) {
	r := NewPeerRegistry(t.TempDir())
	r.Register("default", "p1", "127.0.0.1:9001", []string{"digest-a"}, "host-a", "2.0.0")
	r.Heartbeat("default", "p1", 7, []string{"digest-c"})

	peers := r.Discover("default", "", true)
	if len(peers) != 1 {
		t.Fatalf("Discover = %d peers, want 1", len(peers))
	}
	if got := peers[0]["blob_count"]; got != 7 {
		t.Fatalf("blob_count = %v, want 7", got)
	}
	blobs, ok := peers[0]["blobs"].([]string)
	if !ok || len(blobs) != 1 || blobs[0] != "digest-c" {
		t.Fatalf("心跳未刷新 blobs: %v", peers[0]["blobs"])
	}

	r.Unregister("default", "p1")
	if got := r.Discover("default", "", false); len(got) != 0 {
		t.Fatalf("注销后仍有 %d 个节点", len(got))
	}
}

func TestPeerExpiryAndExclude(t *testing.T) {
	r := NewPeerRegistry(t.TempDir())
	f := &peersFile{Peers: []*Peer{{
		PeerID: "stale", Vault: "default", Listen: "127.0.0.1:9000",
		LastSeen: nowFloat() - PeerTTL - 10, BlobCount: 1,
	}}}
	if err := r.save(f); err != nil {
		t.Fatal(err)
	}
	if got := r.Discover("default", "", false); len(got) != 0 {
		t.Fatalf("过期节点未被剔除: %d", len(got))
	}

	r.Register("default", "fresh", "127.0.0.1:9003", nil, "host-c", "2.0.0")
	if got := r.Discover("default", "fresh", false); len(got) != 0 {
		t.Fatal("exclude 未排除指定节点")
	}
	if got := r.Discover("default", "", false); len(got) != 1 {
		t.Fatalf("新节点未被发现: %d", len(got))
	}
}
