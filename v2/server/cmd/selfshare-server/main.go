// Command selfshare-server 是协议兼容 Go 服务端。
//
// 数据目录、SQLite 元数据、blob 布局、server.json / paircodes.json / peers.json
// 都与 Python 实现逐字节相同，因此两种实现可以直接换着跑同一份数据。
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"selfshare/server/internal/api"
	"selfshare/server/internal/store"
)

// 发行版本；注意与 HTTP 层的 ServiceVersion（协议版本）区分。
const serverVersion = "2.0.0"

// banner 首行与 Python 服务端逐字一致，方便部署脚本按同一标记判定就绪。
const banner = `SelfShare server listening on %s
  data root : %s
  vaults    : %s
  engine    : go`

func main() {
	var (
		root  = flag.String("root", "selfshare-data", "数据根目录")
		host  = flag.String("host", "0.0.0.0", "监听地址")
		port  = flag.Int("port", 8484, "监听端口，0 表示随机")
		cert  = flag.String("cert", "", "TLS 证书路径")
		key   = flag.String("key", "", "TLS 私钥路径")
		quiet = flag.Bool("quiet", false, "不打印访问日志与配对码")
		showVersion = flag.Bool("version", false, "打印版本号并退出")
	)
	flag.Parse()

	if *showVersion {
		fmt.Println("selfshare-server " + serverVersion)
		return
	}

	if err := run(*root, *host, *port, *cert, *key, *quiet); err != nil {
		fmt.Fprintln(os.Stderr, "selfshare-server:", err)
		os.Exit(1)
	}
}

func run(root, host string, port int, cert, key string, quiet bool) error {
	srv, err := api.New(root, quiet)
	if err != nil {
		return err
	}
	if err := ensureFirstVault(srv); err != nil {
		return err
	}

	scheme := "http"
	if cert != "" {
		scheme = "https"
	}
	addr := net.JoinHostPort(host, fmt.Sprint(port))
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	display := displayHost(host)
	_, actualPort, _ := net.SplitHostPort(ln.Addr().String())
	publicURL := scheme + "://" + display + ":" + actualPort
	fmt.Printf(banner+"\n", publicURL, absOrSelf(root), joinOrNone(srv.Registry.ListVaults()))
	if err := printPairingCode(srv, publicURL, quiet); err != nil {
		return err
	}
	fmt.Println("  press Ctrl+C to stop")

	httpSrv := &http.Server{
		Handler: srv,
		// 大文件上传可能很慢，只给读头设超时
		ReadHeaderTimeout: 30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
	shutdownLater(httpSrv, srv)

	if cert != "" {
		err = httpSrv.ServeTLS(ln, cert, key)
	} else {
		err = httpSrv.Serve(ln)
	}
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

// ensureFirstVault 复刻 Python 的零配置起步：一个库都没有时自动建 default。
func ensureFirstVault(srv *api.Server) error {
	if len(srv.Registry.ListVaults()) > 0 {
		return nil
	}
	if _, err := srv.Registry.CreateVault("default", "auto-created", ""); err != nil {
		return err
	}
	fmt.Println("  已自动创建同步库: default")
	return nil
}

// printPairingCode 在服务就绪后发一张配对码；失败不应影响服务启动。
func printPairingCode(srv *api.Server, publicURL string, quiet bool) error {
	if quiet {
		return nil
	}
	vaults := srv.Registry.ListVaults()
	if len(vaults) == 0 {
		return nil
	}
	first := vaults[0]
	code, _, err := store.NewPairCodeStore(srv.Registry.VaultPath(first)).
		Issue(first, 1800, "启动自动生成")
	if err != nil {
		fmt.Println("  （配对码生成失败：" + err.Error() + "）")
		return nil
	}
	fmt.Println()
	fmt.Println("  ┌──────────────────────────────────────────────┐")
	fmt.Println("  │  在另一台设备上连接（配对码 30 分钟内有效）  │")
	fmt.Println("  └──────────────────────────────────────────────┘")
	fmt.Println("     地址  : " + publicURL)
	fmt.Println("     配对码: " + code)
	fmt.Println()
	fmt.Println("     桌面端：打开 SelfShare → 「连接同步文件夹」→ 填入上面两项")
	fmt.Println("     命令行：selfshare pair <同步文件夹> --url " + publicURL + " --code " + code)
	fmt.Println()
	return nil
}

// displayHost 与 Python 一致：绑全网卡时打印一个对外可达的 IPv4。
func displayHost(host string) string {
	if host != "0.0.0.0" && host != "" && host != "::" {
		return host
	}
	name, err := os.Hostname()
	if err != nil {
		return "127.0.0.1"
	}
	addrs, err := net.LookupHost(name)
	if err != nil {
		return "127.0.0.1"
	}
	for _, a := range addrs {
		if ip := net.ParseIP(a); ip != nil && ip.To4() != nil && !ip.IsLoopback() {
			return a
		}
	}
	return "127.0.0.1"
}

func absOrSelf(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		return path
	}
	return abs
}

func joinOrNone(vaults []string) string {
	if len(vaults) == 0 {
		return "(none yet)"
	}
	out := vaults[0]
	for _, v := range vaults[1:] {
		out += ", " + v
	}
	return out
}

// shutdownLater 收到中断后停止接新连接并退出。
func shutdownLater(httpSrv *http.Server, srv *api.Server) {
	sig := make(chan os.Signal, 2)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sig
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = httpSrv.Shutdown(ctx)
	}()
}
