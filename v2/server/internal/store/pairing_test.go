package store

import (
	"strings"
	"testing"
	"time"
)

// placeholderCodeBody 是 SS-XXXX-XXXX-XXXX 形态的占位码体，仅用于测试；
// 避免真实形态配对码出现在代码里（AGENTS.md §5.4）。
const placeholderCodeBody = "XXXXXXXXXXXX"

func TestPairCodeIssueAndRedeemOnce(t *testing.T) {
	p := NewPairCodeStore(t.TempDir())
	code, expires, err := p.Issue("default", 600, "unit-test")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	if !strings.HasPrefix(code, "SS-") {
		t.Fatalf("配对码格式不符: %q", code)
	}
	if expires <= float64(time.Now().UnixNano())/1e9 {
		t.Fatal("兑换期限应落在未来")
	}
	if got := len(p.ListActive("default")); got != 1 {
		t.Fatalf("ListActive = %d, want 1", got)
	}

	// 客户端粘贴时常见的小写 / 空格 / 缺连字符也应能兑换。
	loose := strings.ToLower(strings.ReplaceAll(code, "-", " "))
	vault, note, ok := p.Redeem(loose)
	if !ok || vault != "default" || note != "unit-test" {
		t.Fatalf("Redeem = (%q, %q, %v)", vault, note, ok)
	}
	if _, _, ok := p.Redeem(code); ok {
		t.Fatal("一次性配对码被重复兑换")
	}
	if got := len(p.ListActive("default")); got != 0 {
		t.Fatalf("兑换后仍有 %d 张有效码", got)
	}
}

func TestPairCodeExpiryAndRevoke(t *testing.T) {
	p := NewPairCodeStore(t.TempDir())
	if _, _, err := p.Issue("v1", 600, "a"); err != nil {
		t.Fatal(err)
	}
	if _, _, err := p.Issue("v2", 600, "b"); err != nil {
		t.Fatal(err)
	}
	if n := p.RevokeAll("v1"); n != 1 {
		t.Fatalf("RevokeAll = %d, want 1", n)
	}
	if got := len(p.ListActive("v1")); got != 0 {
		t.Fatalf("吊销后仍有 %d 张有效码", got)
	}

	// 盘上注入一张已过期码，Redeem 必须拒绝并清理。
	f, err := p.load()
	if err != nil {
		t.Fatal(err)
	}
	now := float64(time.Now().UnixNano()) / 1e9
	f.Codes[placeholderCodeBody] = &pairCode{
		Vault: "v2", CreatedAt: now - 100, ExpiresAt: now - 1, Note: "expired",
	}
	if err := p.save(f); err != nil {
		t.Fatal(err)
	}
	if _, _, ok := p.Redeem(FormatCode(placeholderCodeBody)); ok {
		t.Fatal("过期配对码被兑换")
	}
}

func TestNormaliseAndFormatCode(t *testing.T) {
	if got := NormaliseCode(" ss-xxxx-xxxx-xxxx "); got != placeholderCodeBody {
		t.Fatalf("NormaliseCode = %q", got)
	}
	if got := FormatCode(placeholderCodeBody); got != "SS-XXXX-XXXX-XXXX" {
		t.Fatalf("FormatCode = %q", got)
	}
}
