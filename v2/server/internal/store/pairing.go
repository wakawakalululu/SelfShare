package store

import (
	"crypto/rand"
	"encoding/json"
	"math/big"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	codePrefix   = "SS"
	codeGroup    = 4
	codeGroups   = 3
	codeFile     = "paircodes.json"
	defaultTTL   = 1800.0
	maxTTL       = 86400.0
	minTTL       = 60.0
	codeAlphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
)

type pairCode struct {
	Vault     string   `json:"vault"`
	CreatedAt float64  `json:"created_at"`
	ExpiresAt float64  `json:"expires_at"`
	Used      bool     `json:"used"`
	Note      string   `json:"note"`
	UsedAt    *float64 `json:"used_at,omitempty"`
}

type pairFile struct {
	Codes map[string]*pairCode `json:"codes"`
}

// PairCodeStore 与 Python 的 PairCodeStore 共用同一个 paircodes.json。
type PairCodeStore struct {
	path string
	mu   sync.Mutex
}

func NewPairCodeStore(vaultRoot string) *PairCodeStore {
	return &PairCodeStore{path: filepath.Join(vaultRoot, codeFile)}
}

// NormaliseCode 容忍空格、小写与缺少分组符；与 Python 一致地削掉 SS 前缀。
func NormaliseCode(code string) string {
	var b strings.Builder
	for _, ch := range strings.ToUpper(code) {
		if (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') {
			b.WriteRune(ch)
		}
	}
	text := b.String()
	text = strings.TrimPrefix(text, codePrefix)
	return text
}

// FormatCode 统一显示成 SS-XXXX-XXXX-XXXX。
func FormatCode(code string) string {
	body := NormaliseCode(code)
	groups := make([]string, 0, codeGroups)
	for i := 0; i < len(body); i += codeGroup {
		end := i + codeGroup
		if end > len(body) {
			end = len(body)
		}
		groups = append(groups, body[i:end])
	}
	return codePrefix + "-" + strings.Join(groups, "-")
}

func randomCode() string {
	out := make([]byte, codeGroup*codeGroups)
	for i := range out {
		n, err := rand.Int(rand.Reader, big.NewInt(int64(len(codeAlphabet))))
		if err != nil {
			panic(err)
		}
		out[i] = codeAlphabet[n.Int64()]
	}
	s := string(out)
	groups := make([]string, 0, codeGroups)
	for i := 0; i < len(s); i += codeGroup {
		groups = append(groups, s[i:i+codeGroup])
	}
	return strings.Join(groups, "-")
}

func (s *PairCodeStore) load() (*pairFile, error) {
	raw, err := os.ReadFile(s.path)
	if os.IsNotExist(err) {
		return &pairFile{Codes: map[string]*pairCode{}}, nil
	}
	if err != nil {
		return nil, err
	}
	var f pairFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, err
	}
	if f.Codes == nil {
		f.Codes = map[string]*pairCode{}
	}
	return &f, nil
}

func (s *PairCodeStore) save(f *pairFile) error {
	payload, err := marshalSorted(f)
	if err != nil {
		return err
	}
	return AtomicWrite(s.path, payload)
}

// Issue 生成一次性配对码；ttl 被钳在 [60s, 24h]，与 Python 行为一致。
func (s *PairCodeStore) Issue(vaultID string, ttl float64, note string) (string, float64, error) {
	if ttl <= 0 {
		ttl = defaultTTL
	}
	if ttl < minTTL {
		ttl = minTTL
	}
	if ttl > maxTTL {
		ttl = maxTTL
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return "", 0, err
	}
	code := randomCode()
	key := NormaliseCode(code)
	now := float64(time.Now().UnixNano()) / 1e9
	f.Codes[key] = &pairCode{
		Vault:     vaultID,
		CreatedAt: now,
		ExpiresAt: now + ttl,
		Note:      note,
	}
	if err := s.save(f); err != nil {
		return "", 0, err
	}
	return FormatCode(code), now + ttl, nil
}

// Redeem 兑换配对码：一次性、过期即删，返回所属同步库。
func (s *PairCodeStore) Redeem(code string) (string, string, bool) {
	key := NormaliseCode(code)
	if key == "" {
		return "", "", false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return "", "", false
	}
	item, ok := f.Codes[key]
	if !ok || item.Used {
		return "", "", false
	}
	if item.ExpiresAt < float64(time.Now().UnixNano())/1e9 {
		delete(f.Codes, key)
		_ = s.save(f)
		return "", "", false
	}
	usedAt := float64(time.Now().UnixNano()) / 1e9
	item.Used = true
	item.UsedAt = &usedAt
	if err := s.save(f); err != nil {
		return "", "", false
	}
	return item.Vault, item.Note, true
}

type activeCode struct {
	Code      string  `json:"code"`
	ExpiresIn float64 `json:"expires_in"`
	Note      string  `json:"note"`
}

// ListActive 列出未使用且未过期的配对码。
func (s *PairCodeStore) ListActive(vaultID string) []activeCode {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return nil
	}
	now := float64(time.Now().UnixNano()) / 1e9
	out := make([]activeCode, 0)
	for raw, item := range f.Codes {
		if item.Vault != vaultID || item.Used || item.ExpiresAt < now {
			continue
		}
		out = append(out, activeCode{
			Code:      FormatCode(raw),
			ExpiresIn: item.ExpiresAt - now,
			Note:      item.Note,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ExpiresIn < out[j].ExpiresIn })
	return out
}

// RevokeAll 吊销该同步库的全部配对码，返回吊销数量。
func (s *PairCodeStore) RevokeAll(vaultID string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return 0
	}
	before := len(f.Codes)
	for key, item := range f.Codes {
		if item.Vault == vaultID {
			delete(f.Codes, key)
		}
	}
	removed := before - len(f.Codes)
	if removed > 0 {
		_ = s.save(f)
	}
	return removed
}
