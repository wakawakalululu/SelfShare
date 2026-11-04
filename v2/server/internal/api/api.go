// Package api 提供与 Python 服务端逐请求兼容的 HTTP 层。
//
// 路由（除 ping/pair 外都要 Bearer 令牌）:
//
//	GET  /api/ping
//	GET  /api/pair            只回显服务信息
//	POST /api/pair            配对码换令牌
//	*    /api/v/<vault>/manifest|commit|history|stat|blobbulk|blob|peers|peer
package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"selfshare/server/internal/store"
)

const (
	// MaxBody 与 Python 的 MAX_BODY 一致：单个 blob 上限 2 GiB。
	MaxBody = 2 * 1024 * 1024 * 1024
	// CommitOpsMax 与 Python 的 <=5000 items 校验一致。
	CommitOpsMax = 5000
	// ServiceVersion 保持 "1.0"，老客户端按它做协议判断。
	ServiceVersion = "1.0"
)

// StatusError 对应 Python 的 HandlerError。
type StatusError struct {
	Code int
	Msg  string
}

func (e *StatusError) Error() string { return e.Msg }

func fail(code int, format string, args ...any) *StatusError {
	return &StatusError{Code: code, Msg: fmt.Sprintf(format, args...)}
}

// Server 是同步服务的 HTTP 处理器。
type Server struct {
	Registry *store.Registry
	Quiet    bool
}

func New(root string, quiet bool) (*Server, error) {
	reg, err := store.NewRegistry(root)
	if err != nil {
		return nil, err
	}
	return &Server{Registry: reg, Quiet: quiet}, nil
}

// vault 每次请求打开一个句柄，与 Python 服务端一致：
// 服务端进程不长期持有 vault.db，Windows 上 vault remove / 整目录拷贝才不会被占用。
func (s *Server) vault(vaultID string) (*store.Vault, error) {
	return store.OpenVault(vaultID, s.Registry.VaultPath(vaultID))
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if err := s.route(w, r); err != nil {
		s.writeError(w, r, err)
	}
}

func (s *Server) route(w http.ResponseWriter, r *http.Request) error {
	parsed := r.URL
	raw := strings.Split(strings.Trim(parsed.Path, "/"), "/")
	parts := make([]string, 0, len(raw))
	for _, p := range raw {
		if p != "" {
			parts = append(parts, p)
		}
	}
	q := parsed.Query()

	if len(parts) >= 2 && parts[0] == "api" && parts[1] == "ping" {
		return writeJSON(w, http.StatusOK, map[string]any{
			"ok": true, "service": "selfshare", "version": ServiceVersion,
			"engine": "go", "vaults": len(s.Registry.ListVaults()), "time": nowISO(),
		})
	}
	if len(parts) >= 2 && parts[0] == "api" && parts[1] == "pair" {
		if r.Method == http.MethodPost {
			return s.handlePair(w, r)
		}
		if r.Method == http.MethodGet {
			return writeJSON(w, http.StatusOK, map[string]any{
				"ok": true, "service": "selfshare", "version": ServiceVersion, "pairing": true,
			})
		}
		return fail(http.StatusMethodNotAllowed, "method not allowed")
	}
	if len(parts) < 4 || parts[0] != "api" || parts[1] != "v" {
		return fail(404, "unknown endpoint %s", r.URL.Path)
	}
	vaultID := parts[2]
	// 与 Python 一致：先判存在性再鉴权，避免用 401 泄露路由差异
	if !store.ValidVaultID(vaultID) || !s.Registry.Exists(vaultID) {
		return fail(404, "no such vault: '%s'", vaultID)
	}
	if err := s.authorise(r, vaultID); err != nil {
		return err
	}
	action := parts[3]
	rest := parts[4:]
	// 纯文件/P2P 发现的请求不需要 SQLite，使用轻量句柄避免每次开关数据库；
	// 涉及 manifest/commit/history/stat 的请求仍走完整 Vault（按需打开，用完即关）。
	var (
		v   *store.Vault
		err error
	)
	if action == "blob" || action == "blobbulk" || action == "peers" || action == "peer" {
		v, err = store.OpenBlobStore(vaultID, s.Registry.VaultPath(vaultID))
	} else {
		v, err = s.vault(vaultID)
	}
	if err != nil {
		return err
	}
	defer v.Close()

	switch {
	case action == "manifest" && (r.Method == "GET" || r.Method == "HEAD"):
		since, cerr := parseInt(q.Get("since"), 0)
		if cerr != nil {
			return fail(400, "invalid since: %q", q.Get("since"))
		}
		entries, head, merr := v.Manifest(since)
		if merr != nil {
			return merr
		}
		return writeJSON(w, http.StatusOK, map[string]any{"head_rev": head, "entries": entries})

	case action == "commit" && r.Method == http.MethodPost:
		var req struct {
			Origin string     `json:"origin"`
			Ops    []store.Op `json:"ops"`
		}
		if err := readJSON(r, &req); err != nil {
			return fail(400, "commit body must be JSON")
		}
		if len(req.Ops) > CommitOpsMax {
			return fail(400, "ops must be a list of <=%d items", CommitOpsMax)
		}
		res, cerr := v.Commit(req.Ops, req.Origin)
		if cerr != nil {
			return translate(cerr)
		}
		return writeJSON(w, http.StatusOK, res)

	case action == "history" && (r.Method == "GET" || r.Method == "HEAD"):
		limit, cerr := parseInt(q.Get("limit"), 50)
		if cerr != nil {
			return fail(400, "invalid limit: %q", q.Get("limit"))
		}
		items, herr := v.History(q.Get("path"), int(limit))
		if herr != nil {
			return translate(herr)
		}
		return writeJSON(w, http.StatusOK, map[string]any{"entries": items})

	case action == "stat" && (r.Method == "GET" || r.Method == "HEAD"):
		st, serr := v.Stat()
		if serr != nil {
			return serr
		}
		return writeJSON(w, http.StatusOK, st)

	case action == "blobbulk" && r.Method == http.MethodPost:
		return s.handleBlobBulk(w, r, v)

	case action == "blob" && len(rest) == 1:
		digest := strings.ToLower(rest[0])
		switch r.Method {
		case http.MethodPut:
			return s.handlePutBlob(w, r, v, digest)
		case http.MethodGet, http.MethodHead:
			return s.handleGetBlob(w, r, v, digest)
		default:
			return fail(http.StatusMethodNotAllowed, "method not allowed")
		}

	case action == "peers" && r.Method == http.MethodGet:
		withBlobs := q.Get("with_blobs") == "1" || q.Get("with_blobs") == "true"
		peers := store.NewPeerRegistry(s.Registry.VaultPath(vaultID)).
			Discover(vaultID, q.Get("exclude"), withBlobs)
		if peers == nil {
			peers = []map[string]any{}
		}
		return writeJSON(w, http.StatusOK, map[string]any{"peers": peers})

	case action == "peer" && len(rest) == 1 && r.Method == http.MethodPost:
		return s.handlePeer(w, r, vaultID, rest[0])
	}
	return fail(404, "unknown endpoint %s", r.URL.Path)
}

func (s *Server) authorise(r *http.Request, vaultID string) error {
	header := r.Header.Get("Authorization")
	token := ""
	if len(header) >= 7 && strings.EqualFold(header[:7], "bearer ") {
		token = strings.TrimSpace(header[7:])
	}
	if token == "" {
		token = strings.TrimSpace(r.Header.Get("X-Vault-Token"))
	}
	if !s.Registry.CheckToken(vaultID, token) {
		return fail(401, "invalid or missing token")
	}
	return nil
}

// writeError 把错误映射成 {"error": ...}，与 Python 的 except 链一致。
func (s *Server) writeError(w http.ResponseWriter, r *http.Request, err error) {
	var se *StatusError
	if errors.As(err, &se) {
		_ = writeJSON(w, se.Code, map[string]any{"error": se.Msg})
		return
	}
	if errors.Is(err, store.ErrConflict) {
		_ = writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error()})
		return
	}
	var notFound *os.PathError
	if errors.As(err, &notFound) {
		_ = writeJSON(w, http.StatusNotFound, map[string]any{
			"error": "not found: " + notFound.Err.Error()})
		return
	}
	if !s.Quiet {
		fmt.Fprintf(os.Stderr, "[selfshare-go] %s %s: %v\n", nowISO(), r.RemoteAddr, err)
	}
	_ = writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "internal error"})
}

func translate(err error) error {
	if errors.Is(err, store.ErrConflict) {
		return err
	}
	// 路径规范化一类的错误在 Python 侧走 ValueError -> 400
	if strings.Contains(err.Error(), "must not contain") {
		return &StatusError{Code: http.StatusBadRequest, Msg: err.Error()}
	}
	return err
}

func writeJSON(w http.ResponseWriter, code int, v any) error {
	payload, err := marshalNoHTMLEscape(v)
	if err != nil {
		return err
	}
	h := w.Header()
	h.Set("Content-Type", "application/json; charset=utf-8")
	h.Set("Content-Length", strconv.Itoa(len(payload)))
	w.WriteHeader(code)
	_, err = w.Write(payload)
	return err
}

func readJSON(r *http.Request, target any) error {
	body, err := readBody(r, MaxBody)
	if err != nil {
		return err
	}
	if len(body) == 0 {
		body = []byte("{}")
	}
	return json.Unmarshal(body, target)
}

func readBody(r *http.Request, limit int64) ([]byte, error) {
	if r.ContentLength > limit {
		return nil, fail(413, "body too large")
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(body)) > limit {
		return nil, fail(413, "body too large")
	}
	return body, nil
}

func parseInt(raw string, def int64) (int64, error) {
	if raw == "" {
		return def, nil
	}
	return strconv.ParseInt(raw, 10, 64)
}

func nowISO() string { return time.Now().Format("2006-01-02 15:04:05") }
