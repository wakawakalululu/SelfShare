package api

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"selfshare/server/internal/store"
)

type harness struct {
	t          *testing.T
	ts         *httptest.Server
	srv        *Server
	vault, tok string
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	srv, err := New(t.TempDir(), true)
	if err != nil {
		t.Fatal(err)
	}
	token, err := srv.Registry.CreateVault("lab", "test", "")
	if err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(srv)
	t.Cleanup(ts.Close)
	return &harness{t: t, ts: ts, srv: srv, vault: "lab", tok: token}
}

func (h *harness) do(method, path string, body []byte, headers map[string]string) *http.Response {
	h.t.Helper()
	req, err := http.NewRequest(method, h.ts.URL+path, bytes.NewReader(body))
	if err != nil {
		h.t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+h.tok)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		h.t.Fatal(err)
	}
	h.t.Cleanup(func() { resp.Body.Close() })
	return resp
}

func (h *harness) jsonBody(path string) map[string]any {
	h.t.Helper()
	resp := h.do("GET", path, nil, nil)
	if resp.StatusCode != 200 {
		h.t.Fatalf("GET %s -> %d", path, resp.StatusCode)
	}
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		h.t.Fatal(err)
	}
	return out
}

func (h *harness) putBlob(data []byte) string {
	h.t.Helper()
	digest := store.Sha256Bytes(data)
	resp := h.do("PUT", "/api/v/"+h.vault+"/blob/"+digest, data, nil)
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		h.t.Fatalf("PUT blob -> %d %s", resp.StatusCode, b)
	}
	return digest
}

func (h *harness) commit(ops ...store.Op) map[string]any {
	h.t.Helper()
	payload, _ := json.Marshal(map[string]any{"origin": "go-test", "ops": ops})
	req, _ := http.NewRequest("POST", h.ts.URL+"/api/v/"+h.vault+"/commit", bytes.NewReader(payload))
	req.Header.Set("Authorization", "Bearer "+h.tok)
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		h.t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode != 200 {
		h.t.Fatalf("commit -> %d %+v", resp.StatusCode, out)
	}
	return out
}

func ptr(s string) *string { return &s }

func ptrTo[T any](v T) *T { return &v }

func TestPingAndAuth(t *testing.T) {
	h := newHarness(t)
	resp := h.do("GET", "/api/ping", nil, nil)
	if resp.StatusCode != 200 {
		t.Fatalf("ping -> %d", resp.StatusCode)
	}
	bad := h.do("GET", "/api/v/lab/stat", nil, map[string]string{"Authorization": "Bearer nope"})
	if bad.StatusCode != 401 {
		t.Fatalf("wrong token -> %d, want 401", bad.StatusCode)
	}
	// X-Vault-Token 备选头
	req, _ := http.NewRequest("GET", h.ts.URL+"/api/v/lab/stat", nil)
	req.Header.Set("X-Vault-Token", h.tok)
	resp2, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != 200 {
		t.Fatalf("X-Vault-Token -> %d", resp2.StatusCode)
	}
	// 未知 vault 与未知路由
	if c := h.do("GET", "/api/v/ghost/stat", nil, nil); c.StatusCode != 404 {
		t.Fatalf("ghost vault -> %d", c.StatusCode)
	}
	if c := h.do("GET", "/api/nonsense", nil, nil); c.StatusCode != 404 {
		t.Fatalf("unknown route -> %d", c.StatusCode)
	}
}

func TestManifestCommitAndConflictWire(t *testing.T) {
	h := newHarness(t)
	digest := h.putBlob([]byte("v1"))
	res := h.commit(store.Op{Op: "put", Path: "docs/a.txt", Hash: ptr(digest), Size: ptrTo(int64(2))})
	if applied, _ := res["applied"].([]any); len(applied) != 1 {
		t.Fatalf("applied: %+v", res)
	}
	man := h.jsonBody("/api/v/lab/manifest?since=0")
	entries, _ := man["entries"].([]any)
	if len(entries) != 1 || man["head_rev"].(float64) != 1 {
		t.Fatalf("manifest: %+v", man)
	}
	row := entries[0].(map[string]any)
	if row["path"] != "docs/a.txt" || row["hash"] != digest || row["deleted"].(bool) {
		t.Fatalf("manifest row: %+v", row)
	}
	// 过期 base_hash 走 200 + conflicts，而不是 5xx
	stale := h.commit(store.Op{Op: "put", Path: "docs/a.txt", Hash: ptr(digest), BaseHash: ptr("deadbeef")})
	if conflicts, _ := stale["conflicts"].([]any); len(conflicts) != 0 {
		t.Fatalf("identical content must stay silent: %+v", stale)
	}
	// 路径穿越 -> 400
	payload, _ := json.Marshal(map[string]any{"ops": []any{
		map[string]any{"op": "put", "path": "../evil", "hash": digest}}})
	req, _ := http.NewRequest("POST", h.ts.URL+"/api/v/lab/commit", bytes.NewReader(payload))
	req.Header.Set("Authorization", "Bearer "+h.tok)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("traversal commit -> %d, want 400", resp.StatusCode)
	}
}

func TestBlobPutMismatchAndRange(t *testing.T) {
	h := newHarness(t)
	good := h.putBlob([]byte("0123456789abcdef"))
	if c := h.do("PUT", "/api/v/lab/blob/"+good, []byte("tampered"), nil); c.StatusCode == 200 {
		t.Fatal("digest mismatch must not be accepted")
	}
	// 声明摘要与字节不符 -> 400（与 Python 一致）
	resp := h.do("PUT", "/api/v/lab/blob/"+store.Sha256Bytes([]byte("other")), []byte("payload"), nil)
	var errBody map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&errBody)
	if resp.StatusCode != 400 {
		t.Fatalf("declared mismatch -> %d %v", resp.StatusCode, errBody)
	}

	// HEAD 只回头，不带 body
	head := h.do("HEAD", "/api/v/lab/blob/"+good, nil, nil)
	if head.StatusCode != 200 || head.ContentLength != 16 {
		t.Fatalf("HEAD blob -> %d len=%d", head.StatusCode, head.ContentLength)
	}
	if body, _ := io.ReadAll(head.Body); len(body) != 0 {
		t.Fatalf("HEAD must have empty body, got %q", body)
	}
	// Range
	ranged := h.do("GET", "/api/v/lab/blob/"+good, nil, map[string]string{"Range": "bytes=4-7"})
	if ranged.StatusCode != 206 {
		t.Fatalf("range -> %d", ranged.StatusCode)
	}
	if got := ranged.Header.Get("Content-Range"); got != "bytes 4-7/16" {
		t.Fatalf("Content-Range: %q", got)
	}
	data, _ := io.ReadAll(ranged.Body)
	if string(data) != "4567" {
		t.Fatalf("range body: %q", data)
	}
	if c := h.do("GET", "/api/v/lab/blob/"+good, nil, map[string]string{"Range": "bytes=99-100"}); c.StatusCode != 416 {
		t.Fatalf("unsatisfiable range -> %d", c.StatusCode)
	}
}

func TestBlobBulkIsolatesFailures(t *testing.T) {
	h := newHarness(t)
	keep := store.Sha256Bytes([]byte("keep"))
	good := h.putBlob([]byte("keep"))
	if good != keep {
		t.Fatalf("digest helper drifted")
	}
	items := []map[string]any{
		{"hash": store.Sha256Bytes([]byte("n1")), "data": b64("n1")},
		{"hash": keep, "data": b64("keep")}, // 已存在
		{"hash": store.Sha256Bytes([]byte("bad")), "data": b64("other")},
		{"hash": "ZZZ", "data": b64("x")},
		{"hash": store.Sha256Bytes([]byte("n2")), "data": "!!!not base64!!!"},
	}
	payload, _ := json.Marshal(map[string]any{"blobs": items})
	req, _ := http.NewRequest("POST", h.ts.URL+"/api/v/lab/blobbulk", bytes.NewReader(payload))
	req.Header.Set("Authorization", "Bearer "+h.tok)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out struct {
		Stored  []string `json:"stored"`
		Existed []string `json:"existed"`
		Failed  []struct {
			Hash  string `json:"hash"`
			Error string `json:"error"`
		} `json:"failed"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode != 200 || len(out.Stored) != 1 || len(out.Existed) != 1 || len(out.Failed) != 3 {
		t.Fatalf("bulk result: %+v", out)
	}
	want := map[string]string{"bad digest": "", "bad base64": "", "digest mismatch": ""}
	for _, f := range out.Failed {
		known := false
		for prefix := range want {
			if len(f.Error) >= len(prefix) && f.Error[:len(prefix)] == prefix {
				known = true
			}
		}
		if !known {
			t.Fatalf("unexpected bulk failure: %+v", f)
		}
	}
	// 成功项必须真的落盘
	manifest := h.jsonBody("/api/v/lab/manifest?since=0")
	_ = manifest
	if c := h.do("GET", "/api/v/lab/blob/"+store.Sha256Bytes([]byte("n1")), nil, nil); c.StatusCode != 200 {
		t.Fatalf("stored blob missing -> %d", c.StatusCode)
	}
}

func TestPairingCodeExchange(t *testing.T) {
	h := newHarness(t)
	code, _, err := store.NewPairCodeStore(h.srv.Registry.VaultPath(h.vault)).
		Issue(h.vault, 1800, "from-test")
	if err != nil {
		t.Fatal(err)
	}
	// 配对是唯一无需令牌的写接口
	payload, _ := json.Marshal(map[string]any{"code": code})
	req, _ := http.NewRequest("POST", h.ts.URL+"/api/pair", bytes.NewReader(payload))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out struct {
		Vault string `json:"vault"`
		Token string `json:"token"`
		Note  string `json:"note"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode != 200 || out.Vault != h.vault || out.Token != h.tok {
		t.Fatalf("pair -> %d %+v", resp.StatusCode, out)
	}
	if out.Note != "from-test" {
		t.Fatalf("pair note: %+v", out)
	}
	// 一次性：第二次兑换必须 404
	req2, _ := http.NewRequest("POST", h.ts.URL+"/api/pair", bytes.NewReader(payload))
	resp2, err := http.DefaultClient.Do(req2)
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != 404 {
		t.Fatalf("replay of a redeemed code -> %d", resp2.StatusCode)
	}
	// 兑换回来的令牌真的可用
	req3, _ := http.NewRequest("GET", h.ts.URL+"/api/v/lab/stat", nil)
	req3.Header.Set("Authorization", "Bearer "+out.Token)
	resp3, err := http.DefaultClient.Do(req3)
	if err != nil {
		t.Fatal(err)
	}
	defer resp3.Body.Close()
	if resp3.StatusCode != 200 {
		t.Fatalf("paired token stat -> %d", resp3.StatusCode)
	}
}

func TestPeersRegisterDiscoverHeartbeat(t *testing.T) {
	h := newHarness(t)
	post := func(action string, body map[string]any) map[string]any {
		payload, _ := json.Marshal(body)
		req, _ := http.NewRequest("POST", h.ts.URL+"/api/v/"+h.vault+"/peer/"+action,
			bytes.NewReader(payload))
		req.Header.Set("Authorization", "Bearer "+h.tok)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var out map[string]any
		_ = json.NewDecoder(resp.Body).Decode(&out)
		if resp.StatusCode != 200 {
			t.Fatalf("%s -> %d %+v", action, resp.StatusCode, out)
		}
		return out
	}
	reg := post("register", map[string]any{
		"peer_id": "p1", "listen": "127.0.0.1:9001", "blobs": []string{"aa"},
		"host_id": "hostA", "version": "1.3.0"})
	if reg["registered"] != true || reg["ttl"].(float64) != store.PeerTTL {
		t.Fatalf("register: %+v", reg)
	}
	hb := post("heartbeat", map[string]any{"peer_id": "p1", "blob_count": 1})
	if hb["ok"] != true {
		t.Fatalf("heartbeat: %+v", hb)
	}
	miss := post("heartbeat", map[string]any{"peer_id": "ghost", "blob_count": 0})
	if miss["ok"] != false {
		t.Fatalf("unknown peer heartbeat: %+v", miss)
	}
	peers := h.jsonBody("/api/v/lab/peers")
	list, _ := peers["peers"].([]any)
	if len(list) != 1 {
		t.Fatalf("peers: %+v", peers)
	}
	if _, hasBlobs := list[0].(map[string]any)["blobs"]; hasBlobs {
		t.Fatal("default discover must omit blob lists")
	}
	full := h.jsonBody("/api/v/lab/peers?with_blobs=1")
	if _, hasBlobs := full["peers"].([]any)[0].(map[string]any)["blobs"]; !hasBlobs {
		t.Fatal("with_blobs must include blob lists")
	}
	unreg := post("unregister", map[string]any{"peer_id": "p1"})
	if unreg["ok"] != true {
		t.Fatalf("unregister: %+v", unreg)
	}
	if after := h.jsonBody("/api/v/lab/peers")["peers"]; len(after.([]any)) != 0 {
		t.Fatalf("peers after unregister: %+v", after)
	}
}

func TestHistoryLimitClampAndStat(t *testing.T) {
	h := newHarness(t)
	d1 := h.putBlob([]byte("one"))
	d2 := h.putBlob([]byte("two"))
	h.commit(store.Op{Op: "put", Path: "f.txt", Hash: ptr(d1)})
	h.commit(store.Op{Op: "put", Path: "f.txt", Hash: ptr(d2), BaseHash: ptr(d1)})
	hist := h.jsonBody("/api/v/lab/history?limit=500&path=f.txt")
	entries, _ := hist["entries"].([]any)
	if len(entries) != 2 {
		t.Fatalf("history: %+v", hist)
	}
	newest := entries[0].(map[string]any)
	if newest["rev"].(float64) != 2 || newest["hash"] != d2 || newest["action"] != "put" {
		t.Fatalf("newest version: %+v", newest)
	}
	if newest["time"] == nil || fmt.Sprint(newest["time"]) == "" {
		t.Fatalf("history must format time: %+v", newest)
	}
	st := h.jsonBody("/api/v/lab/stat")
	if st["files"].(float64) != 1 || st["blobs"].(float64) != 2 || st["head_rev"].(float64) != 2 {
		t.Fatalf("stat: %+v", st)
	}
}

func b64(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }
