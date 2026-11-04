#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VERSION="${VERSION:-2.0.0-dev}"

echo "=== SelfShare v${VERSION} Build ==="
echo "Project root: ${PROJECT_ROOT}"

build_server() {
    echo ""
    echo "--- Building Go Server ---"
    cd "${PROJECT_ROOT}/server"

    local os=$1
    local arch=$2
    local ext=""
    [ "$os" = "windows" ] && ext=".exe"

    echo "  Target: ${os}/${arch}"
    CGO_ENABLED=0 GOOS=${os} GOARCH=${arch} \
        go build -trimpath -ldflags="-s -w" \
        -o "bin/selfshare-server-${os}-${arch}${ext}" \
        ./cmd/selfshare-server

    echo "  Output: bin/selfshare-server-${os}-${arch}${ext}"
}

build_client() {
    echo ""
    echo "--- Building Tauri Client ---"
    cd "${PROJECT_ROOT}/client"

    echo "  Installing npm dependencies..."
    npm install --silent

    echo "  Building Tauri app..."
    npm run tauri build

    echo "  Client build complete"
}

case "${1:-all}" in
    server-linux)
        build_server linux amd64
        build_server linux arm64
        ;;
    server-windows)
        build_server windows amd64
        ;;
    server-darwin)
        build_server darwin amd64
        build_server darwin arm64
        ;;
    server-all)
        build_server linux amd64
        build_server linux arm64
        build_server windows amd64
        build_server darwin amd64
        build_server darwin arm64
        ;;
    client)
        build_client
        ;;
    all)
        build_server linux amd64
        build_server windows amd64
        build_client
        ;;
    *)
        echo "Usage: $0 {server-linux|server-windows|server-darwin|server-all|client|all}"
        exit 1
        ;;
esac

echo ""
echo "=== Build complete ==="
