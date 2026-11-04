# syntax=docker/dockerfile:1

# ---- 构建阶段 ----
FROM golang:1.24-alpine AS builder

# server-go 用纯 Go 的 modernc.org/sqlite，无需 cgo / gcc。
RUN apk add --no-cache ca-certificates tzdata

WORKDIR /src

# 先只拷 go.mod/go.sum，依赖层可被缓存复用。
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# 二进制不注入 version/commit（该 main.go 未定义这些变量），只做体积裁剪。
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
    -o /out/selfshare-server ./cmd/selfshare-server

# ---- 运行阶段 ----
# 选 alpine 而非 scratch：healthcheck 需要 wget，且便于容器内排查。
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata \
    && adduser -D -u 10001 selfshare

COPY --from=builder /out/selfshare-server /usr/local/bin/selfshare-server

VOLUME ["/data"]
EXPOSE 8484

# 容器自带存活检查；端口随 CMD 改变时请同步调整此处。
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8484/api/ping > /dev/null || exit 1

USER selfshare
WORKDIR /data

# server-go 只认命令行参数，不读 SELFSHARE_* 环境变量：用 CMD 传参。
ENTRYPOINT ["/usr/local/bin/selfshare-server"]
CMD ["--root", "/data", "--host", "0.0.0.0", "--port", "8484"]
