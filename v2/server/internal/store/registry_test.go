package store

import (
	"path/filepath"
	"testing"
)

func TestRegistryCreateAndToken(t *testing.T) {
	root := t.TempDir()
	r, err := NewRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	token, err := r.CreateVault("default", "unit", "tok-unit-1234567890abcdef")
	if err != nil {
		t.Fatalf("CreateVault: %v", err)
	}
	if !r.CheckToken("default", token) {
		t.Fatal("显式令牌校验失败")
	}
	if r.CheckToken("default", "wrong-token-1234567890") {
		t.Fatal("错误令牌被接受")
	}
	if !r.Exists("default") || len(r.ListVaults()) != 1 {
		t.Fatal("注册表未正确列出同步库")
	}
	if _, err := r.CreateVault("default", "dup", ""); err == nil {
		t.Fatal("重复建库未被拒绝")
	}
	if ValidVaultID("../escape") || !ValidVaultID("work_2026") {
		t.Fatal("库名校验规则不符预期")
	}
	if got := r.VaultPath("default"); got != filepath.Join(root, "vaults", "default") {
		t.Fatalf("VaultPath = %q", got)
	}
}

func TestRegistryReloadFromDisk(t *testing.T) {
	root := t.TempDir()
	r, err := NewRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	token, err := r.CreateVault("shared", "", "tok-shared-1234567890abcdef")
	if err != nil {
		t.Fatal(err)
	}
	// 另一个进程（例如 Python CLI 或重启后的 Go 服务端）读同一份 server.json。
	r2, err := NewRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	if !r2.Exists("shared") || !r2.CheckToken("shared", token) {
		t.Fatal("磁盘上的注册表 / 令牌无法被新实例读取")
	}
	if got := r2.CurrentToken("shared"); got != token {
		t.Fatal("密封令牌还原失败，配对流程将无法下发真实令牌")
	}
}
