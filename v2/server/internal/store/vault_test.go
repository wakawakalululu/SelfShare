package store

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func tempVault(t *testing.T) *Vault {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "vaults", "default")
	v, err := OpenVault("default", dir)
	if err != nil {
		t.Fatalf("open vault: %v", err)
	}
	t.Cleanup(func() { _ = v.Close() })
	return v
}

func strPtr(s string) *string { return &s }

func putOp(path, digest string, base *string) Op {
	return Op{Op: "put", Path: path, Hash: strPtr(digest), BaseHash: base}
}

func TestCommitPutConflictAndNoOp(t *testing.T) {
	v := tempVault(t)
	a, _ := v.PutBlobBytes([]byte("aaa"))
	b, _ := v.PutBlobBytes([]byte("bbb"))

	res, err := v.Commit([]Op{putOp("x.txt", a, nil)}, "host1")
	if err != nil || len(res.Applied) != 1 || res.HeadRev != 1 {
		t.Fatalf("first put: res=%+v err=%v", res, err)
	}

	// 内容未变 -> 静默跳过，不产生新版本
	res, err = v.Commit([]Op{putOp("x.txt", a, strPtr(a))}, "host1")
	if err != nil || len(res.Applied) != 0 || len(res.Conflicts) != 0 || res.HeadRev != 1 {
		t.Fatalf("identical put must be no-op: res=%+v err=%v", res, err)
	}

	// base_hash 落后 -> 冲突且不覆盖
	res, err = v.Commit([]Op{putOp("x.txt", b, strPtr("stale"))}, "host2")
	if err != nil || len(res.Conflicts) != 1 || res.Conflicts[0].Reason != "remote_changed" {
		t.Fatalf("stale base must conflict: res=%+v err=%v", res, err)
	}
	entries, _, _ := v.Manifest(0)
	if len(entries) != 1 || *entries[0].Hash != a {
		t.Fatalf("conflict must not overwrite: %+v", entries)
	}

	// 缺少 blob -> ErrConflict（Python 侧 409）
	const absent = "0000000000000000000000000000000000000000000000000000000000000000"
	if _, err := v.Commit([]Op{putOp("y.txt", absent, nil)}, "h"); !errors.Is(err, ErrConflict) {
		t.Fatalf("missing blob must be ErrConflict, got %v", err)
	}
}

func TestCommitDeleteTombstoneAndForceResurrect(t *testing.T) {
	v := tempVault(t)
	d, _ := v.PutBlobBytes([]byte("payload"))
	if _, err := v.Commit([]Op{putOp("a/b.txt", d, nil)}, "h1"); err != nil {
		t.Fatal(err)
	}
	// 别人删了，我方 base 仍指向旧内容 -> 删除冲突
	if _, err := v.Commit([]Op{{Op: "del", Path: "a/b.txt", BaseHash: strPtr(d)}}, "h2"); err != nil {
		t.Fatal(err)
	}
	entries, _, _ := v.Manifest(0)
	if len(entries) != 1 || !entries[0].Deleted {
		t.Fatalf("del must leave tombstone: %+v", entries)
	}
	// base 为 nil 时删除才生效
	res, err := v.Commit([]Op{{Op: "del", Path: "a/b.txt"}}, "h2")
	if err != nil || len(res.Applied) != 0 {
		t.Fatalf("repeat del is a no-op: res=%+v err=%v", res, err)
	}
	// force 复活被删路径
	res, err = v.Commit([]Op{{Op: "put", Path: "a/b.txt", Hash: strPtr(d), Force: true}}, "h1")
	if err != nil || len(res.Applied) != 1 {
		t.Fatalf("force must resurrect: res=%+v err=%v", res, err)
	}
	if st, err := v.Stat(); err != nil || st.Files != 1 || st.Versions != 3 || st.HeadRev != 3 {
		t.Fatalf("stat after resurrect: %+v err=%v", st, err)
	}
}

func TestHeadRevMonotonicAndVersionsAppendOnly(t *testing.T) {
	v := tempVault(t)
	a, _ := v.PutBlobBytes([]byte("v1"))
	b, _ := v.PutBlobBytes([]byte("v2"))

	// 第一次有效提交：head_rev 0 -> 1，versions 落 1 条。
	res1, err := v.Commit([]Op{putOp("hist.txt", a, nil)}, "h1")
	if err != nil || len(res1.Applied) != 1 || res1.HeadRev != 1 {
		t.Fatalf("first commit: res=%+v err=%v", res1, err)
	}
	if got := v.HeadRev(); got != 1 {
		t.Fatalf("HeadRev after first commit = %d, want 1", got)
	}
	st1, err := v.Stat()
	if err != nil || st1.HeadRev != 1 || st1.Versions != 1 {
		t.Fatalf("stat after first commit: %+v err=%v", st1, err)
	}
	h1, err := v.History("hist.txt", 10)
	if err != nil || len(h1) != 1 || h1[0].Rev != 1 || h1[0].Action != "put" {
		t.Fatalf("history after first commit: %+v err=%v", h1, err)
	}

	// 第二次提交改写同一路径：head_rev 必须严格递增，旧版本条目不得被清理/改写。
	res2, err := v.Commit([]Op{putOp("hist.txt", b, strPtr(a))}, "h2")
	if err != nil || len(res2.Applied) != 1 || res2.HeadRev <= res1.HeadRev {
		t.Fatalf("second commit: res=%+v err=%v", res2, err)
	}
	if got := v.HeadRev(); got != res2.HeadRev || got <= res1.HeadRev {
		t.Fatalf("HeadRev = %d, want %d (> %d)", got, res2.HeadRev, res1.HeadRev)
	}
	st2, err := v.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if st2.HeadRev <= st1.HeadRev {
		t.Fatalf("Stat.HeadRev not monotonic: %d -> %d", st1.HeadRev, st2.HeadRev)
	}
	if st2.Versions <= st1.Versions {
		t.Fatalf("versions must be append-only: %d -> %d", st1.Versions, st2.Versions)
	}

	// History 按 id DESC 返回；两条版本都必须还在，且 rev 单调递增。
	h2, err := v.History("hist.txt", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(h2) != 2 {
		t.Fatalf("history must retain both revisions, got %d: %+v", len(h2), h2)
	}
	if h2[0].Rev != res2.HeadRev || h2[1].Rev != res1.HeadRev || h2[0].Rev <= h2[1].Rev {
		t.Fatalf("history revs not append-only/monotonic: %+v", h2)
	}
	if h2[1].Hash == nil || *h2[1].Hash != a {
		t.Fatalf("first revision was rewritten/lost: %+v", h2[1])
	}

	// Manifest(since=0) 的 head_rev 回参与 HeadRev() 一致。
	_, manifestRev, err := v.Manifest(0)
	if err != nil || manifestRev != v.HeadRev() {
		t.Fatalf("Manifest head_rev = %d, HeadRev = %d, err=%v", manifestRev, v.HeadRev(), err)
	}
}

func TestCommitRejectsTraversal(t *testing.T) {
	v := tempVault(t)
	d, _ := v.PutBlobBytes([]byte("x"))
	if _, err := v.Commit([]Op{putOp("../escape.txt", d, nil)}, "h"); err == nil {
		t.Fatal("traversal path must error")
	}
}

func TestBlobStreamVerifiesDigest(t *testing.T) {
	v := tempVault(t)
	data := []byte("hello world")
	good := Sha256Bytes(data)
	if _, err := v.WriteBlobStream(good, bytes.NewReader(data)); err != nil {
		t.Fatalf("valid stream: %v", err)
	}
	if !v.HasBlob(good) {
		t.Fatal("blob missing after stream write")
	}
	if _, err := v.WriteBlobStream(Sha256Bytes([]byte("other")), bytes.NewReader(data)); !errors.Is(err, ErrDigestMismatch) {
		t.Fatalf("mismatch must be ErrDigestMismatch, got %v", err)
	}
	// 半截文件不能改名到位
	tmp := filepath.Join(v.BlobRoot, "00")
	if entries, _ := os.ReadDir(tmp); len(entries) != 0 {
		t.Fatalf("failed write left files behind: %v", entries)
	}
}

func TestNormRelAndAbsPathContainment(t *testing.T) {
	root := filepath.Join("data", "vault")
	if got, err := NormRel(".\\a\\./b//c/"); err != nil || got != "a/b/c" {
		t.Fatalf("NormRel windows: %q %v", got, err)
	}
	if got, _ := NormRel("./a/../b"); got != "" {
		t.Fatalf("NormRel must reject traversal, got %q", got)
	}
	if _, err := AbsPath(root, "blobs/../../etc/passwd"); err == nil {
		t.Fatal("AbsPath must reject escape")
	}
	got, err := AbsPath(root, "blobs/ab/abcd")
	if err != nil || filepath.Clean(got) != filepath.Clean(filepath.Join(root, "blobs", "ab", "abcd")) {
		t.Fatalf("AbsPath: %q %v", got, err)
	}

	// 表驱动补充：盘符 / 绝对路径 / .. 逃逸 / 正常相对路径。
	// 期望值按 AbsPath 的契约构造（NormRel → filepath.Join），
	// 并显式核对结果仍在 root 内，防止 containment 回归。
	cleanRoot := filepath.Clean(root) + string(os.PathSeparator)
	cases := []struct {
		name     string
		rel      string
		wantNorm string // NormRel 的期望输出；wantErr 时为 ""
		wantErr  bool
	}{
		{"windows drive letter is a plain relative segment", "C:/Windows/x.txt", "C:/Windows/x.txt", false},
		{"windows-style absolute path is normalised", "C:\\Windows\\x.txt", "C:/Windows/x.txt", false},
		{"posix absolute path is normalised", "/etc/passwd", "etc/passwd", false},
		{"parent traversal is rejected", "blobs/../../etc/passwd", "", true},
		{"bare dotdot is rejected", "..", "", true},
		{"nested dotdot is rejected", "a/../b/../../c", "", true},
		{"normal relative path", "blobs/ab/abcd", "blobs/ab/abcd", false},
		{"dot and empty segments are collapsed", ".\\a\\./b//c/", "a/b/c", false},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			norm, normErr := NormRel(tc.rel)
			if tc.wantErr {
				if normErr == nil {
					t.Fatalf("NormRel(%q) = %q, want error", tc.rel, norm)
				}
				if _, err := AbsPath(root, tc.rel); err == nil {
					t.Fatalf("AbsPath(%q) must reject escape", tc.rel)
				}
				return
			}
			if normErr != nil || norm != tc.wantNorm {
				t.Fatalf("NormRel(%q) = %q, %v; want %q", tc.rel, norm, normErr, tc.wantNorm)
			}
			out, err := AbsPath(root, tc.rel)
			if err != nil {
				t.Fatalf("AbsPath(%q) must stay inside root: %v", tc.rel, err)
			}
			want := filepath.Join(root, filepath.FromSlash(tc.wantNorm))
			if filepath.Clean(out) != filepath.Clean(want) {
				t.Fatalf("AbsPath(%q) = %q, want %q", tc.rel, out, want)
			}
			if !strings.HasPrefix(filepath.Clean(out)+string(os.PathSeparator), cleanRoot) {
				t.Fatalf("AbsPath(%q) escaped root: %q", tc.rel, out)
			}
		})
	}
}
