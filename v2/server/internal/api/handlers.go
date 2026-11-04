package api

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"selfshare/server/internal/store"
)

const (
	// 与 Python 的 BULK_MAX_ITEMS / BULK_MAX_ITEM_BYTES 一致。
	bulkMaxItems    = 512
	bulkMaxItemLen  = 4 * 1024 * 1024
	copyChunk       = 1 << 20
	sealKeyFileMode = 0o600
)

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

// handlePair 用一次性配对码换取令牌；这是唯一不需要令牌的写接口。
func (s *Server) handlePair(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		Code string `json:"code"`
	}
	if err := readJSON(r, &req); err != nil {
		return fail(400, "body must be JSON")
	}
	if strings.TrimSpace(req.Code) == "" {
		return fail(400, "code is required")
	}
	for _, vaultID := range s.Registry.ListVaults() {
		pairFile := filepath.Join(s.Registry.VaultPath(vaultID), "paircodes.json")
		_, note, ok := store.NewPairCodeStore(filepath.Dir(pairFile)).Redeem(req.Code)
		if !ok {
			continue
		}
		token := s.Registry.CurrentToken(vaultID)
		if token == "" {
			return fail(http.StatusConflict, "vault token unavailable; rotate it")
		}
		return writeJSON(w, http.StatusOK, map[string]any{
			"vault": vaultID, "token": token, "note": note,
		})
	}
	return fail(404, "配对码无效、已使用或已过期")
}

// handleBlobBulk 一次请求写入多个小 blob；单项失败只影响该项。
func (s *Server) handleBlobBulk(w http.ResponseWriter, r *http.Request, v *store.Vault) error {
	var req struct {
		Blobs []map[string]any `json:"blobs"`
	}
	body, err := readBody(r, MaxBody)
	if err != nil {
		return err
	}
	if len(body) == 0 {
		body = []byte("{}")
	}
	if json.Unmarshal(body, &req) != nil {
		return fail(400, "bulk body must be JSON")
	}
	if req.Blobs == nil {
		return fail(400, "blobs must be a list")
	}
	if len(req.Blobs) > bulkMaxItems {
		return fail(413, "too many blobs in one batch")
	}
	type failure struct {
		Hash  string `json:"hash"`
		Error string `json:"error"`
	}
	stored := make([]string, 0, len(req.Blobs))
	existed := make([]string, 0, 8)
	failed := make([]failure, 0, 4)

	for _, item := range req.Blobs {
		digest := strings.ToLower(asString(item["hash"]))
		if !hex64.MatchString(digest) {
			short := digest
			if len(short) > 64 {
				short = short[:64]
			}
			failed = append(failed, failure{short, "bad digest"})
			continue
		}
		data, derr := base64.StdEncoding.DecodeString(asString(item["data"]))
		if derr != nil {
			failed = append(failed, failure{digest, "bad base64"})
			continue
		}
		if len(data) > bulkMaxItemLen {
			failed = append(failed, failure{digest, "item too large for bulk"})
			continue
		}
		actual := store.Sha256Bytes(data)
		if actual != digest {
			failed = append(failed, failure{digest, "digest mismatch: body " + actual})
			continue
		}
		if v.HasBlob(digest) {
			existed = append(existed, digest)
			continue
		}
		if _, perr := v.PutBlobBytes(data); perr != nil {
			failed = append(failed, failure{digest, perr.Error()})
			continue
		}
		stored = append(stored, digest)
	}
	return writeJSON(w, http.StatusOK, map[string]any{
		"stored": stored, "existed": existed, "failed": failed,
	})
}

// handlePutBlob 流式接收 blob，不把大文件整块读进内存。
func (s *Server) handlePutBlob(w http.ResponseWriter, r *http.Request, v *store.Vault, digest string) error {
	if !hex64.MatchString(digest) {
		return &StatusError{409, "bad blob digest"}
	}
	size, err := v.WriteBlobStream(digest, io.LimitReader(r.Body, MaxBody+1))
	if err != nil {
		if errors.Is(err, store.ErrDigestMismatch) {
			return fail(400, "digest mismatch: declared %s, body %s",
				digest, declaredActual(err))
		}
		if r.ContentLength > MaxBody || size > MaxBody {
			return fail(413, "body too large")
		}
		return err
	}
	return writeJSON(w, http.StatusOK, map[string]any{
		"ok": true, "hash": digest, "size": size,
	})
}

// handleGetBlob 支持单段 Range，响应头与 Python 逐字一致。
func (s *Server) handleGetBlob(w http.ResponseWriter, r *http.Request, v *store.Vault, digest string) error {
	path, err := v.BlobPath(digest)
	if err != nil {
		return &StatusError{409, "bad blob digest"}
	}
	st, err := os.Stat(path)
	if err != nil {
		return fail(404, "blob not found")
	}
	total := st.Size()
	var start, end int64 = 0, total - 1
	rangeHeader := r.Header.Get("Range")
	if strings.HasPrefix(rangeHeader, "bytes=") {
		lo, hi, _ := strings.Cut(strings.TrimSpace(strings.Split(rangeHeader[6:], ",")[0]), "-")
		bad := false
		if lo != "" {
			if n, perr := strconv.ParseInt(lo, 10, 64); perr == nil {
				start = n
			} else {
				bad = true
			}
		}
		if hi != "" {
			n, perr := strconv.ParseInt(hi, 10, 64)
			if perr != nil {
				bad = true
			} else if n < total {
				end = n
			}
		}
		if bad {
			start, end = 0, total-1
		}
	}
	if start > end || start >= total {
		return fail(416, "range not satisfiable")
	}
	length := end - start + 1
	code := http.StatusOK
	if rangeHeader != "" {
		code = http.StatusPartialContent
	}
	h := w.Header()
	h.Set("Content-Type", "application/octet-stream")
	h.Set("Content-Length", strconv.FormatInt(length, 10))
	h.Set("Accept-Ranges", "bytes")
	if rangeHeader != "" {
		h.Set("Content-Range",
			"bytes "+strconv.FormatInt(start, 10)+"-"+strconv.FormatInt(end, 10)+
				"/"+strconv.FormatInt(total, 10))
	}
	// HEAD 必须由服务端抑制 body；这里显式返回以免读出文件。
	w.WriteHeader(code)
	if r.Method == http.MethodHead || length <= 0 {
		return nil
	}
	f, err := os.Open(path)
	if err != nil {
		return fail(404, "blob not found")
	}
	defer f.Close()
	if _, err := f.Seek(start, io.SeekStart); err != nil {
		return err
	}
	_, err = copyN(w, f, length)
	return err
}

func (s *Server) handlePeer(w http.ResponseWriter, r *http.Request,
	vaultID, sub string) error {
	var req map[string]any
	if err := readJSON(r, &req); err != nil {
		return fail(400, "peer body must be JSON")
	}
	if req == nil {
		req = map[string]any{}
	}
	preg := store.NewPeerRegistry(s.Registry.VaultPath(vaultID))
	switch sub {
	case "register":
		blobs := asStrings(req["blobs"])
		res := preg.Register(vaultID, asString(req["peer_id"]), asString(req["listen"]),
			blobs, asString(req["host_id"]), asString(req["version"]))
		return writeJSON(w, http.StatusOK, res)
	case "heartbeat":
		var blobs []string
		if raw, ok := req["blobs"].([]any); ok {
			blobs = asStrings(raw)
			if blobs == nil {
				blobs = []string{}
			}
		}
		res := preg.Heartbeat(vaultID, asString(req["peer_id"]), asInt(req["blob_count"]), blobs)
		return writeJSON(w, http.StatusOK, res)
	case "unregister":
		return writeJSON(w, http.StatusOK, preg.Unregister(vaultID, asString(req["peer_id"])))
	}
	return fail(404, "unknown peer action %s", sub)
}

func copyN(dst io.Writer, src io.Reader, n int64) (int64, error) {
	return io.Copy(dst, io.LimitReader(src, n))
}

func declaredActual(err error) string {
	msg := err.Error()
	if i := strings.LastIndex(msg, "body "); i >= 0 {
		return strings.TrimSpace(msg[i+5:])
	}
	return msg
}

func asString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func asInt(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case string:
		i, _ := strconv.Atoi(n)
		return i
	}
	return 0
}

func asStrings(v any) []string {
	raw, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		out = append(out, asString(item))
	}
	return out
}

func marshalNoHTMLEscape(v any) ([]byte, error) {
	var buf strings.Builder
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return []byte(strings.TrimRight(buf.String(), "\n")), nil
}
