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

// TestCommitDeleteVsEditConflicts 覆盖 AGENTS.md §6「删除与编辑相撞」两向。
// 断言以 v2/server/internal/store/vault.go:276-317 的实读语义为准：本层只做
// base_hash 乐观并发，冲突方记入 CommitResult.Conflicts(reason=remote_changed)
// 并跳过，不生成「名字 (冲突副本-从 主机 时间).ext」副本（副本命名在
// desktop/core/src/engine.rs:46,407）。因此服务端层面的「不丢数据」表现为：
// 远端条目不被静默覆盖、head_rev 不回退、versions 不减少；A 改 / B 删保留
// 编辑，A 删 / B 改可由编辑方 Force 重放复活。
func TestCommitDeleteVsEditConflicts(t *testing.T) {
	const path = "dir/clash.txt"

	cases := []struct {
		name        string
		firstDel    bool // true: A 删 / B 改；false: A 改 / B 删
		wantDeleted bool // 相撞后 files 表是否为 tombstone
	}{
		{"A deletes, B edits", true, true},
		{"A edits, B deletes", false, false},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			v := tempVault(t)
			base, err := v.PutBlobBytes([]byte("base-v1"))
			if err != nil {
				t.Fatal(err)
			}
			edited, err := v.PutBlobBytes([]byte("edited-v2"))
			if err != nil {
				t.Fatal(err)
			}

			// 双方共同基线：一次普通 put，head_rev=1、versions=1。
			res0, err := v.Commit([]Op{putOp(path, base, nil)}, "host-setup")
			if err != nil || len(res0.Applied) != 1 || res0.HeadRev != 1 {
				t.Fatalf("baseline put: res=%+v err=%v", res0, err)
			}

			// 两方基于同一 base 同时动作。
			var first, second Op
			if tc.firstDel {
				first = Op{Op: "del", Path: path, BaseHash: strPtr(base)}
				second = putOp(path, edited, strPtr(base))
			} else {
				first = putOp(path, edited, strPtr(base))
				second = Op{Op: "del", Path: path, BaseHash: strPtr(base)}
			}

			resA, err := v.Commit([]Op{first}, "hostA")
			if err != nil || len(resA.Applied) != 1 || len(resA.Conflicts) != 0 ||
				resA.HeadRev <= res0.HeadRev {
				t.Fatalf("first party must apply: res=%+v err=%v", resA, err)
			}
			stA, err := v.Stat()
			if err != nil {
				t.Fatal(err)
			}
			hA, err := v.History(path, 10)
			if err != nil || len(hA) != 2 {
				t.Fatalf("history after first commit: %+v err=%v", hA, err)
			}

			// 相撞方：必须显式报冲突，不得静默覆盖，也不得 bump head_rev / 追加版本。
			resB, err := v.Commit([]Op{second}, "hostB")
			if err != nil || len(resB.Applied) != 0 || len(resB.Conflicts) != 1 {
				t.Fatalf("clash must be reported, not overwritten: res=%+v err=%v", resB, err)
			}
			c := resB.Conflicts[0]
			if c.Path != path || c.Reason != "remote_changed" || c.RemoteRev != resA.HeadRev {
				t.Fatalf("unexpected conflict: %+v (first head_rev=%d)", c, resA.HeadRev)
			}
			if tc.firstDel {
				// 已被删的路径：current 为 nil，remote_hash 必须为空。
				if c.RemoteHash != nil {
					t.Fatalf("deleted path must report nil remote_hash: %+v", c)
				}
			} else if c.RemoteHash == nil || *c.RemoteHash != edited {
				t.Fatalf("edited path must report remote_hash=%s: %+v", edited, c)
			}
			if resB.HeadRev != resA.HeadRev || v.HeadRev() != resA.HeadRev {
				t.Fatalf("head_rev must not move on a rejected op: %d -> %d", resA.HeadRev, resB.HeadRev)
			}
			stB, err := v.Stat()
			if err != nil {
				t.Fatal(err)
			}
			if stB.HeadRev < stA.HeadRev || stB.Versions < stA.Versions {
				t.Fatalf("head_rev/versions must never regress: %+v -> %+v", stA, stB)
			}
			if stB.HeadRev != stA.HeadRev || stB.Versions != stA.Versions {
				t.Fatalf("rejected clash op must not bump rev/version: %+v -> %+v", stA, stB)
			}
			hB, err := v.History(path, 10)
			if err != nil || len(hB) != len(hA) || hB[0].Rev != hA[0].Rev ||
				hB[1].Hash == nil || *hB[1].Hash != base {
				t.Fatalf("rejected op must not rewrite/append versions: %+v -> %+v err=%v", hA, hB, err)
			}

			// Manifest 只保留原路径这一条（store 层不生成冲突副本），且远端内容未被覆盖。
			entries, manifestRev, err := v.Manifest(0)
			if err != nil || manifestRev != v.HeadRev() || len(entries) != 1 ||
				entries[0].Path != path {
				t.Fatalf("manifest after clash: entries=%+v rev=%d err=%v", entries, manifestRev, err)
			}
			if entries[0].Deleted != tc.wantDeleted {
				t.Fatalf("deleted flag after clash = %v, want %v: %+v", entries[0].Deleted, tc.wantDeleted, entries[0])
			}
			if tc.wantDeleted {
				if entries[0].Hash != nil {
					t.Fatalf("tombstone must not keep a hash: %+v", entries[0])
				}
			} else if entries[0].Hash == nil || *entries[0].Hash != edited {
				t.Fatalf("edit must be kept, not overwritten by del: %+v", entries[0])
			}

			if !tc.firstDel {
				return // A 改 / B 删：编辑已保留，删除被拒，无需复活。
			}

			// A 删 / B 改：B 的编辑内容仍在 blobstore（未丢数据），
			// 编辑方以 Force 重放即可复活为新内容，且 head_rev 递增、versions 追加。
			if !v.HasBlob(edited) {
				t.Fatal("edited blob was lost on clash")
			}
			resF, err := v.Commit([]Op{{
				Op: "put", Path: path, Hash: strPtr(edited), BaseHash: strPtr(base), Force: true,
			}}, "hostB")
			if err != nil || len(resF.Applied) != 1 || resF.Applied[0].Action != "put" ||
				resF.HeadRev <= resB.HeadRev {
				t.Fatalf("force replay must resurrect the edit: res=%+v err=%v", resF, err)
			}
			stF, err := v.Stat()
			if err != nil || stF.HeadRev != resF.HeadRev || stF.Files != 1 ||
				stF.Versions <= stB.Versions {
				t.Fatalf("stat after force replay: %+v err=%v", stF, err)
			}
			hF, err := v.History(path, 10)
			if err != nil || len(hF) != 3 || hF[0].Rev != resF.HeadRev ||
				hF[0].Action != "put" || hF[0].Hash == nil || *hF[0].Hash != edited ||
				hF[1].Action != "del" || hF[2].Action != "put" ||
				hF[2].Hash == nil || *hF[2].Hash != base {
				t.Fatalf("history must be append-only across del + resurrect: %+v err=%v", hF, err)
			}
			finalEntries, _, err := v.Manifest(0)
			if err != nil || len(finalEntries) != 1 || finalEntries[0].Deleted ||
				finalEntries[0].Hash == nil || *finalEntries[0].Hash != edited {
				t.Fatalf("resurrected edit must win: %+v err=%v", finalEntries, err)
			}
		})
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
