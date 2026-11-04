// Package store 是与 Python 服务端逐字节兼容的存储层：
// 同一份数据目录可以被 Python 与 Go 两种实现读写。
package store

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

// VaultInfo 与 Python 端 server.json 里的条目结构一致。
type VaultInfo struct {
	Created     string         `json:"created"`
	Note        string         `json:"note"`
	Salt        string         `json:"salt"`
	TokenSHA256 string         `json:"token_sha256"`
	TokenSealed *SealedToken   `json:"token_sealed,omitempty"`
	Extra       map[string]any `json:"-"`
}

type SealedToken struct {
	Nonce  string `json:"nonce"`
	Cipher string `json:"cipher"`
}

type registryFile struct {
	SealKey string                `json:"_seal_key"`
	Vaults  map[string]*VaultInfo `json:"vaults"`
}

// Registry 管理 server.json：同步库注册表、令牌摘要与可逆密封。
type Registry struct {
	root  string
	file  string
	mu    sync.Mutex
	data  registryFile
	mtime time.Time
}

var vaultIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// ValidVaultID 与 Python 的 valid_vault_id 一致。
func ValidVaultID(id string) bool { return id != "" && vaultIDPattern.MatchString(id) }

func NewRegistry(root string) (*Registry, error) {
	r := &Registry{
		root: root,
		file: filepath.Join(root, "server.json"),
		data: registryFile{Vaults: map[string]*VaultInfo{}},
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	if err := r.load(); err != nil {
		return nil, err
	}
	return r, nil
}

func (r *Registry) load() error {
	raw, err := os.ReadFile(r.file)
	if errors.Is(err, os.ErrNotExist) {
		r.data = registryFile{Vaults: map[string]*VaultInfo{}}
		r.mtime = time.Time{}
		return nil
	}
	if err != nil {
		return err
	}
	var f registryFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return fmt.Errorf("解析 %s 失败: %w", r.file, err)
	}
	if f.Vaults == nil {
		f.Vaults = map[string]*VaultInfo{}
	}
	r.data = f
	if st := statOf(r.file); !st.IsZero() {
		r.mtime = st
	}
	return nil
}

// refresh 在 server.json 被外部进程（如 selfshare vault create）改动后重新读入。
func (r *Registry) refresh() error {
	st := statOf(r.file)
	if st == r.mtime {
		return nil
	}
	return r.load()
}

func (r *Registry) save() error {
	payload, err := marshalSorted(r.data)
	if err != nil {
		return err
	}
	if err := AtomicWrite(r.file, payload); err != nil {
		return err
	}
	r.mtime = statOf(r.file)
	return nil
}

func (r *Registry) Root() string { return r.root }

func (r *Registry) VaultPath(vaultID string) string {
	return filepath.Join(r.root, "vaults", vaultID)
}

func (r *Registry) ListVaults() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	_ = r.refresh()
	out := make([]string, 0, len(r.data.Vaults))
	for id := range r.data.Vaults {
		out = append(out, id)
	}
	sort.Strings(out)
	return out
}

func (r *Registry) Exists(vaultID string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	_ = r.refresh()
	_, ok := r.data.Vaults[vaultID]
	return ok
}

// CreateVault 生成令牌并写入注册表；令牌只在这里和 RotateToken 的返回值里出现。
func (r *Registry) CreateVault(vaultID, note string, explicitToken string) (string, error) {
	if !ValidVaultID(vaultID) {
		return "", fmt.Errorf("非法同步库名: %q", vaultID)
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := r.refresh(); err != nil {
		return "", err
	}
	if _, ok := r.data.Vaults[vaultID]; ok {
		return "", fmt.Errorf("vault %q already exists", vaultID)
	}
	token := explicitToken
	if token == "" {
		token = randomToken()
	}
	if err := r.checkTokenPolicy(vaultID, token); err != nil {
		return "", err
	}
	key, err := r.sealKey()
	if err != nil {
		return "", err
	}
	salt := randomHex(16)
	info := &VaultInfo{
		Created:     time.Now().Format("2006-01-02 15:04:05"),
		Note:        note,
		Salt:        salt,
		TokenSHA256: digestToken(token, salt),
		TokenSealed: sealToken(token, key),
	}
	r.data.Vaults[vaultID] = info
	if err := os.MkdirAll(filepath.Join(r.VaultPath(vaultID), "blobs"), 0o755); err != nil {
		return "", err
	}
	if err := r.save(); err != nil {
		return "", err
	}
	return token, nil
}

func (r *Registry) checkTokenPolicy(vaultID, token string) error {
	if token == "" {
		return errors.New("token must not be empty")
	}
	if len(token) < 16 {
		return fmt.Errorf("token too short: %d chars", len(token))
	}
	for _, v := range r.data.Vaults {
		if v.TokenSHA256 == digestToken(token, v.Salt) {
			return fmt.Errorf("token already used by vault %q", vaultID)
		}
	}
	return nil
}

// RotateToken 换发新令牌，旧令牌立即失效。
func (r *Registry) RotateToken(vaultID string) (string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := r.refresh(); err != nil {
		return "", err
	}
	info, ok := r.data.Vaults[vaultID]
	if !ok {
		return "", fmt.Errorf("no such vault: %q", vaultID)
	}
	token := randomToken()
	key, err := r.sealKey()
	if err != nil {
		return "", err
	}
	info.Salt = randomHex(16)
	info.TokenSHA256 = digestToken(token, info.Salt)
	info.TokenSealed = sealToken(token, key)
	if err := r.save(); err != nil {
		return "", err
	}
	return token, nil
}

// CheckToken 用常量时间比较校验令牌。
func (r *Registry) CheckToken(vaultID, token string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	_ = r.refresh()
	info, ok := r.data.Vaults[vaultID]
	if !ok {
		return false
	}
	want := digestToken(token, info.Salt)
	return subtle.ConstantTimeCompare([]byte(want), []byte(info.TokenSHA256)) == 1
}

// CurrentToken 还原令牌，供配对码兑换时下发。
func (r *Registry) CurrentToken(vaultID string) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	_ = r.refresh()
	info, ok := r.data.Vaults[vaultID]
	if !ok || info.TokenSealed == nil {
		return ""
	}
	key, err := r.sealKey()
	if err != nil {
		return ""
	}
	return openToken(info.TokenSealed, key)
}

// sealKey 与 Python 端一致：优先用环境变量里的固定密钥，否则落盘一把随机密钥。
func (r *Registry) sealKey() ([]byte, error) {
	if env := os.Getenv("SELFSHARE_SEAL_KEY"); env != "" {
		if raw, err := hex.DecodeString(strings.TrimSpace(env)); err == nil && len(raw) == 32 {
			return raw, nil
		}
		sum := sha256.Sum256([]byte(env))
		return sum[:], nil
	}
	if r.data.SealKey != "" {
		raw, err := hex.DecodeString(r.data.SealKey)
		if err == nil && len(raw) == 32 {
			return raw, nil
		}
	}
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return nil, err
	}
	r.data.SealKey = hex.EncodeToString(raw)
	if err := r.save(); err != nil {
		return nil, err
	}
	return raw, nil
}

func digestToken(token, salt string) string {
	sum := sha256.Sum256([]byte(salt + ":" + token))
	return hex.EncodeToString(sum[:])
}

// keystream 是 SHA-256 计数器模式产生的字节流，与 Python 的 _keystream 逐字节一致。
func keystream(key, nonce []byte, length int) []byte {
	out := make([]byte, 0, length)
	counter := uint64(0)
	for len(out) < length {
		h := sha256.New()
		h.Write(key)
		h.Write(nonce)
		var buf [8]byte
		for i := 0; i < 8; i++ {
			buf[i] = byte(counter >> uint(56-8*i) & 0xff)
		}
		h.Write(buf[:])
		out = append(out, h.Sum(nil)...)
		counter++
	}
	return out[:length]
}

func sealToken(token string, key []byte) *SealedToken {
	nonce := make([]byte, 12)
	if _, err := rand.Read(nonce); err != nil {
		panic(err)
	}
	data := []byte(token)
	stream := keystream(key, nonce, len(data))
	cipher := make([]byte, len(data))
	for i := range data {
		cipher[i] = data[i] ^ stream[i]
	}
	return &SealedToken{Nonce: hex.EncodeToString(nonce), Cipher: hex.EncodeToString(cipher)}
}

func openToken(sealed *SealedToken, key []byte) string {
	nonce, err := hex.DecodeString(sealed.Nonce)
	if err != nil {
		return ""
	}
	cipher, err := hex.DecodeString(sealed.Cipher)
	if err != nil {
		return ""
	}
	stream := keystream(key, nonce, len(cipher))
	raw := make([]byte, len(cipher))
	for i := range cipher {
		raw[i] = cipher[i] ^ stream[i]
	}
	if !isValidUTF8(raw) {
		return ""
	}
	return string(raw)
}

func isValidUTF8(b []byte) bool {
	for _, r := range string(b) {
		if r == 0xfffd {
			return false
		}
	}
	return true
}

// randomToken 与 Python 的 secrets.token_urlsafe(24) 同形：32 字符 base64url 无填充。
func randomToken() string {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(raw)
}

func randomHex(n int) string {
	raw := make([]byte, n)
	if _, err := rand.Read(raw); err != nil {
		panic(err)
	}
	return hex.EncodeToString(raw)
}

func statOf(path string) time.Time {
	st, err := os.Stat(path)
	if err != nil {
		return time.Time{}
	}
	return st.ModTime()
}

// marshalSorted 复现 Python 端 json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)。
// Go 的 map 序列化本身就按键排序，这里只补缩进。
func marshalSorted(v any) ([]byte, error) {
	buf, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return nil, err
	}
	return append(buf, '\n'), nil
}
