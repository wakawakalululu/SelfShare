package store

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

const schema = `
CREATE TABLE IF NOT EXISTS files (
    rel      TEXT PRIMARY KEY,
    hash     TEXT,
    size     INTEGER,
    mtime    REAL,
    rev      INTEGER NOT NULL,
    deleted  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_rev ON files(rev);

CREATE TABLE IF NOT EXISTS versions (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    rel     TEXT NOT NULL,
    hash    TEXT,
    size    INTEGER,
    rev     INTEGER NOT NULL,
    ts      REAL NOT NULL,
    origin  TEXT,
    action  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_rel ON versions(rel, id DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
`

// ErrConflict 表示提交被拒绝且不可自动恢复（对应 Python 的 Conflict）。
var ErrConflict = errors.New("conflict")

// ErrDigestMismatch 表示客户端声明的摘要与收到的字节不符，对应 Python 的 400。
var ErrDigestMismatch = errors.New("digest mismatch")

type Entry struct {
	Path    string   `json:"path"`
	Hash    *string  `json:"hash"`
	Size    *int64   `json:"size"`
	MTime   *float64 `json:"mtime"`
	Rev     int64    `json:"rev"`
	Deleted bool     `json:"deleted"`
}

type Op struct {
	Op       string   `json:"op"`
	Path     string   `json:"path"`
	Hash     *string  `json:"hash"`
	Size     *int64   `json:"size"`
	MTime    *float64 `json:"mtime"`
	BaseHash *string  `json:"base_hash"`
	Force    bool     `json:"force"`
}

type Applied struct {
	Path   string  `json:"path"`
	Hash   *string `json:"hash,omitempty"`
	Rev    int64   `json:"rev"`
	Action string  `json:"action"`
}

type CommitConflict struct {
	Path       string  `json:"path"`
	Reason     string  `json:"reason"`
	RemoteHash *string `json:"remote_hash"`
	RemoteRev  int64   `json:"remote_rev"`
}

type CommitResult struct {
	HeadRev   int64            `json:"head_rev"`
	Applied   []Applied        `json:"applied"`
	Conflicts []CommitConflict `json:"conflicts"`
}

// Vault 是一个独立的同步命名空间；同一份目录可被 Python 与 Go 实现打开。
type Vault struct {
	Root     string
	BlobRoot string

	db *sql.DB
	mu sync.Mutex
}

// OpenBlobStore 返回只用于内容寻址文件的轻量句柄，不打开 SQLite。
// blob 上传/下载与 P2P 节点发现是最高频请求；每个请求都开关一次数据库
// （含 PRAGMA / schema 检查）在 Windows 上尤其昂贵，而这些路径只需 blobs/ 目录。
func OpenBlobStore(vaultID, path string) (*Vault, error) {
	if !ValidVaultID(vaultID) {
		return nil, fmt.Errorf("非法同步库名: %q", vaultID)
	}
	blobRoot := filepath.Join(path, "blobs")
	if err := os.MkdirAll(blobRoot, 0o755); err != nil {
		return nil, err
	}
	return &Vault{Root: path, BlobRoot: blobRoot}, nil
}

func OpenVault(vaultID, path string) (*Vault, error) {
	if !ValidVaultID(vaultID) {
		return nil, fmt.Errorf("非法同步库名: %q", vaultID)
	}
	blobRoot := filepath.Join(path, "blobs")
	if err := os.MkdirAll(blobRoot, 0o755); err != nil {
		return nil, err
	}
	dsn := "file:" + filepath.ToSlash(filepath.Join(path, "vault.db")) +
		"?_pragma=busy_timeout(30000)&_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	// 与 Python 单连接 + 锁的模型一致，避免并发写触发 SQLITE_BUSY
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(schema); err != nil {
		_ = db.Close()
		return nil, err
	}
	if _, err := db.Exec(
		`INSERT INTO meta(key, value) VALUES('head_rev', '0') ON CONFLICT(key) DO NOTHING`); err != nil {
		_ = db.Close()
		return nil, err
	}
	return &Vault{Root: path, BlobRoot: blobRoot, db: db}, nil
}

func (v *Vault) Close() error {
	if v.db == nil {
		return nil
	}
	return v.db.Close()
}

func (v *Vault) BlobPath(digest string) (string, error) {
	if !ValidDigest(digest) {
		return "", fmt.Errorf("%w: bad blob digest", ErrConflict)
	}
	return filepath.Join(v.BlobRoot, digest[:2], digest), nil
}

func (v *Vault) HasBlob(digest string) bool {
	p, err := v.BlobPath(digest)
	if err != nil {
		return false
	}
	_, err = os.Stat(p)
	return err == nil
}

func (v *Vault) BlobSize(digest string) (int64, error) {
	p, err := v.BlobPath(digest)
	if err != nil {
		return 0, err
	}
	st, err := os.Stat(p)
	if err != nil {
		return 0, err
	}
	return st.Size(), nil
}

// PutBlobBytes 写入内容寻址对象；已存在则跳过，返回真实摘要。
func (v *Vault) PutBlobBytes(data []byte) (string, error) {
	digest := Sha256Bytes(data)
	p, err := v.BlobPath(digest)
	if err != nil {
		return "", err
	}
	if _, err := os.Stat(p); err == nil {
		return digest, nil
	}
	if err := AtomicWrite(p, data); err != nil {
		return "", err
	}
	return digest, nil
}

func (v *Vault) OpenBlob(digest string) (*os.File, error) {
	p, err := v.BlobPath(digest)
	if err != nil {
		return nil, err
	}
	f, err := os.Open(p)
	if err != nil {
		return nil, fmt.Errorf("blob not found: %s", digest)
	}
	return f, nil
}

func (v *Vault) HeadRev() int64 {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.headRevLocked()
}

func (v *Vault) headRevLocked() int64 {
	var raw string
	err := v.db.QueryRow(`SELECT value FROM meta WHERE key='head_rev'`).Scan(&raw)
	if err != nil {
		return 0
	}
	var n int64
	if _, scanErr := fmt.Sscanf(raw, "%d", &n); scanErr != nil {
		return 0
	}
	return n
}

// Commit 原子地应用一批操作，语义与 Python 版逐条对应：
// base_hash 是客户端认为的当前内容，不一致即报冲突且不覆盖；
// 内容已相同则静默跳过；force 允许把别人删掉的路径重新建立。
func (v *Vault) Commit(ops []Op, origin string) (*CommitResult, error) {
	v.mu.Lock()
	defer v.mu.Unlock()

	tx, err := v.db.Begin()
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()

	res := &CommitResult{Applied: []Applied{}, Conflicts: []CommitConflict{}}

	for _, op := range ops {
		rel, err := NormRel(op.Path)
		if err != nil {
			return nil, err
		}
		if rel == "" {
			continue
		}
		kind := op.Op
		if kind == "" {
			kind = "put"
		}

		var (
			currentSQL sql.NullString
			rev        int64
			deleted    int
			rowFound   bool
		)
		err = tx.QueryRow(`SELECT hash, rev, deleted FROM files WHERE rel=?`, rel).
			Scan(&currentSQL, &rev, &deleted)
		if err == nil {
			rowFound = true
		} else if !errors.Is(err, sql.ErrNoRows) {
			return nil, err
		}
		current := (*string)(nil)
		if rowFound && deleted == 0 && currentSQL.Valid {
			h := currentSQL.String
			current = &h
		}
		currentRev := rev
		if !rowFound {
			currentRev = 0
		}

		if kind == "del" {
			if current == nil {
				continue
			}
			if op.BaseHash != nil && *current != *op.BaseHash {
				res.Conflicts = append(res.Conflicts, CommitConflict{
					Path: rel, Reason: "remote_changed", RemoteHash: current, RemoteRev: currentRev,
				})
				continue
			}
			newRev, err := v.bump(tx)
			if err != nil {
				return nil, err
			}
			if _, err := tx.Exec(
				`UPDATE files SET hash=NULL, size=NULL, mtime=NULL, rev=?, deleted=1 WHERE rel=?`,
				newRev, rel); err != nil {
				return nil, err
			}
			if err := v.recordVersion(tx, rel, nil, nil, newRev, origin, "del"); err != nil {
				return nil, err
			}
			res.Applied = append(res.Applied, Applied{Path: rel, Rev: newRev, Action: "del"})
			continue
		}

		digest := op.Hash
		if digest == nil || !v.HasBlob(*digest) {
			return nil, fmt.Errorf("%w: blob missing for %s: %v", ErrConflict, rel, deref(digest))
		}

		if !samePtr(current, op.BaseHash) {
			if current != nil && *current == *digest {
				continue
			}
			if !(op.Force && current == nil) {
				res.Conflicts = append(res.Conflicts, CommitConflict{
					Path: rel, Reason: "remote_changed", RemoteHash: current, RemoteRev: currentRev,
				})
				continue
			}
		}
		if current != nil && *current == *digest {
			continue
		}

		newRev, err := v.bump(tx)
		if err != nil {
			return nil, err
		}
		// 与 Python 的 `op.get(...) or 兜底` 一致：0 视为缺省
		size := int64(0)
		if op.Size != nil {
			size = *op.Size
		}
		if size == 0 {
			n, err := v.BlobSize(*digest)
			if err != nil {
				return nil, err
			}
			size = n
		}
		mtime := nowFloat()
		if op.MTime != nil && *op.MTime != 0 {
			mtime = *op.MTime
		}
		if _, err := tx.Exec(
			`INSERT INTO files(rel, hash, size, mtime, rev, deleted) VALUES(?,?,?,?,?,0)
			 ON CONFLICT(rel) DO UPDATE SET hash=excluded.hash, size=excluded.size,
			 mtime=excluded.mtime, rev=excluded.rev, deleted=0`,
			rel, *digest, size, mtime, newRev); err != nil {
			return nil, err
		}
		if err := v.recordVersion(tx, rel, digest, &size, newRev, origin, "put"); err != nil {
			return nil, err
		}
		h := *digest
		res.Applied = append(res.Applied, Applied{Path: rel, Hash: &h, Rev: newRev, Action: "put"})
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	res.HeadRev = v.headRevLocked()
	return res, nil
}

func (v *Vault) bump(tx *sql.Tx) (int64, error) {
	var raw string
	err := tx.QueryRow(`SELECT value FROM meta WHERE key='head_rev'`).Scan(&raw)
	next := int64(1)
	if err == nil {
		var n int64
		if _, scanErr := fmt.Sscanf(raw, "%d", &n); scanErr == nil {
			next = n + 1
		}
	}
	if _, err := tx.Exec(
		`INSERT INTO meta(key, value) VALUES('head_rev', ?)
		 ON CONFLICT(key) DO UPDATE SET value=excluded.value`, fmt.Sprint(next)); err != nil {
		return 0, err
	}
	return next, nil
}

func (v *Vault) recordVersion(tx *sql.Tx, rel string, digest *string, size *int64,
	rev int64, origin, action string) error {
	_, err := tx.Exec(
		`INSERT INTO versions(rel, hash, size, rev, ts, origin, action) VALUES(?,?,?,?,?,?,?)`,
		rel, deref(digest), deref64(size), rev, nowFloat(), origin, action)
	return err
}

// Manifest 返回 rev > since 的条目；since=0 即全量。
func (v *Vault) Manifest(since int64) ([]Entry, int64, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	rows, err := v.db.Query(
		`SELECT rel, hash, size, mtime, rev, deleted FROM files WHERE rev > ? ORDER BY rev ASC`, since)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	out := make([]Entry, 0, 64)
	for rows.Next() {
		var (
			rel     string
			hash    sql.NullString
			size    sql.NullInt64
			mtime   sql.NullFloat64
			rev     int64
			deleted int
		)
		if err := rows.Scan(&rel, &hash, &size, &mtime, &rev, &deleted); err != nil {
			return nil, 0, err
		}
		e := Entry{Path: rel, Rev: rev, Deleted: deleted != 0}
		if hash.Valid {
			h := hash.String
			e.Hash = &h
		}
		if size.Valid {
			s := size.Int64
			e.Size = &s
		}
		if mtime.Valid {
			m := mtime.Float64
			e.MTime = &m
		}
		out = append(out, e)
	}
	return out, v.headRevLocked(), rows.Err()
}

type HistoryItem struct {
	Path   string  `json:"path"`
	Hash   *string `json:"hash"`
	Size   *int64  `json:"size"`
	Rev    int64   `json:"rev"`
	Time   string  `json:"time"`
	Origin string  `json:"origin"`
	Action string  `json:"action"`
}

// History 按时间倒序返回版本记录。
func (v *Vault) History(rel string, limit int) ([]HistoryItem, error) {
	if limit < 1 {
		limit = 1
	}
	if limit > 500 {
		limit = 500
	}
	v.mu.Lock()
	defer v.mu.Unlock()

	var rows *sql.Rows
	var err error
	if rel != "" {
		norm, nerr := NormRel(rel)
		if nerr != nil {
			return nil, nerr
		}
		rows, err = v.db.Query(
			`SELECT rel, hash, size, rev, ts, origin, action FROM versions
			 WHERE rel=? ORDER BY id DESC LIMIT ?`, norm, limit)
	} else {
		rows, err = v.db.Query(
			`SELECT rel, hash, size, rev, ts, origin, action FROM versions
			 ORDER BY id DESC LIMIT ?`, limit)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]HistoryItem, 0, 32)
	for rows.Next() {
		var (
			p, action string
			hash      sql.NullString
			size      sql.NullInt64
			rev       int64
			ts        float64
			origin    sql.NullString
		)
		if err := rows.Scan(&p, &hash, &size, &rev, &ts, &origin, &action); err != nil {
			return nil, err
		}
		item := HistoryItem{
			Path: p, Rev: rev,
			Time:   time.Unix(int64(ts), 0).Format("2006-01-02 15:04:05"),
			Origin: origin.String,
			Action: action,
		}
		if hash.Valid {
			h := hash.String
			item.Hash = &h
		}
		if size.Valid {
			s := size.Int64
			item.Size = &s
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

type Stat struct {
	Files     int64 `json:"files"`
	Bytes     int64 `json:"bytes"`
	Versions  int64 `json:"versions"`
	Blobs     int64 `json:"blobs"`
	BlobBytes int64 `json:"blob_bytes"`
	HeadRev   int64 `json:"head_rev"`
}

// Stat 汇总当前文件数、逻辑容量、版本数与去重后的块数。
func (v *Vault) Stat() (*Stat, error) {
	v.mu.Lock()
	st := &Stat{}
	var liveCount, liveBytes sql.NullInt64
	if err := v.db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(size),0) FROM files WHERE deleted=0`).
		Scan(&liveCount, &liveBytes); err != nil {
		v.mu.Unlock()
		return nil, err
	}
	st.Files = liveCount.Int64
	st.Bytes = liveBytes.Int64
	if err := v.db.QueryRow(`SELECT COUNT(*) FROM versions`).Scan(&st.Versions); err != nil {
		v.mu.Unlock()
		return nil, err
	}
	st.HeadRev = v.headRevLocked()
	v.mu.Unlock()

	err := filepath.Walk(v.BlobRoot, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			return nil
		}
		st.Blobs++
		st.BlobBytes += info.Size()
		return nil
	})
	if err != nil {
		return nil, err
	}
	return st, nil
}

// WriteBlobStream 以流方式接收 blob 并校验摘要，避免把大文件整块读进内存。
// 已存在的对象仍会完整校验声明摘要，坏数据不会被静默接受。
func (v *Vault) WriteBlobStream(digest string, body io.Reader) (int64, error) {
	p, err := v.BlobPath(digest)
	if err != nil {
		return 0, err
	}
	if st, statErr := os.Stat(p); statErr == nil {
		hasher := sha256.New()
		if _, cerr := io.Copy(io.Discard, io.TeeReader(body, hasher)); cerr != nil {
			return 0, cerr
		}
		if actual := hex.EncodeToString(hasher.Sum(nil)); actual != digest {
			return 0, fmt.Errorf("%w: declared %s, body %s", ErrDigestMismatch, digest, actual)
		}
		return st.Size(), nil
	}
	dir := filepath.Dir(p)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return 0, err
	}
	tmp, err := os.CreateTemp(dir, ".selfshare-")
	if err != nil {
		return 0, err
	}
	tmpName := tmp.Name()
	discard := func() {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
	}
	hasher := sha256.New()
	if _, err := io.Copy(tmp, io.TeeReader(body, hasher)); err != nil {
		discard()
		return 0, err
	}
	size, err := tmp.Seek(0, io.SeekCurrent)
	if err != nil {
		discard()
		return 0, err
	}
	if err := tmp.Sync(); err != nil {
		discard()
		return 0, err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName)
		return 0, err
	}
	if actual := hex.EncodeToString(hasher.Sum(nil)); actual != digest {
		_ = os.Remove(tmpName)
		return 0, fmt.Errorf("%w: declared %s, body %s", ErrDigestMismatch, digest, actual)
	}
	if err := os.Rename(tmpName, p); err != nil {
		_ = os.Remove(tmpName)
		return 0, err
	}
	return size, nil
}

func samePtr(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

func deref(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func deref64(p *int64) any {
	if p == nil {
		return nil
	}
	return *p
}
