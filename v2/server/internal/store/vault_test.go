package store

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
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
}
