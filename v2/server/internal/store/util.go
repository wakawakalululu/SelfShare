package store

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// NormRel 与 Python 的 norm_rel 一致：反斜杠转正斜杠、去掉 ./ 与前导 /、
// 丢弃空段与 . 段，任何 .. 段一律拒绝。
func NormRel(rel string) (string, error) {
	text := strings.TrimSpace(strings.ReplaceAll(rel, "\\", "/"))
	for strings.HasPrefix(text, "./") {
		text = text[2:]
	}
	text = strings.TrimLeft(text, "/")
	parts := make([]string, 0, 8)
	for _, p := range strings.Split(text, "/") {
		if p == "" || p == "." {
			continue
		}
		if p == ".." {
			return "", fmt.Errorf("path must not contain '..': %q", rel)
		}
		parts = append(parts, p)
	}
	return strings.Join(parts, "/"), nil
}

// AbsPath 把相对路径安全地拼到 root 之下，并确保结果仍在 root 内。
func AbsPath(root, rel string) (string, error) {
	norm, err := NormRel(rel)
	if err != nil {
		return "", err
	}
	if norm == "" {
		return "", errors.New("empty relative path")
	}
	out := filepath.Join(root, filepath.FromSlash(norm))
	cleanRoot := filepath.Clean(root) + string(os.PathSeparator)
	if !strings.HasPrefix(filepath.Clean(out)+string(os.PathSeparator), cleanRoot) {
		return "", fmt.Errorf("path escapes root: %q", rel)
	}
	return out, nil
}

// AtomicWrite 先写同目录临时文件、fsync 后再改名，避免读到半截内容。
func AtomicWrite(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".selfshare-")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() {
		if _, statErr := os.Stat(tmpName); statErr == nil {
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

func Sha256Bytes(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// ValidDigest 只接受 64 位小写十六进制，避免用路径段做目录穿越。
func ValidDigest(digest string) bool {
	if len(digest) != 64 {
		return false
	}
	for _, c := range digest {
		switch {
		case c >= '0' && c <= '9':
		case c >= 'a' && c <= 'f':
		default:
			return false
		}
	}
	return true
}
