# syntax=docker/dockerfile:1

# ---- 构建阶段 ----
# builder 固定在构建宿主机架构运行，通过 GOARCH 交叉编译目标架构，
# 避免 buildx 多架构构建时用 QEMU 模拟整套 Go 工具链（纯 Go 代码可直接交叉编译）。
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder

# server-go 用纯 Go 的 modernc.org/sqlite，无需 cgo / gcc。
RUN apk add --no-cache ca-certificates tzdata

WORKDIR /src

# 先只拷 go.mod/go.sum，依赖层可被缓存复用。
COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG TARGETOS
ARG TARGETARCH

# 二进制不注入 version/commit（该 main.go 未定义这些变量），只做体积裁剪。
# 普通 docker build 同样会注入 TARGETOS/TARGETARCH；默认值保持与旧行为一致。
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH:-amd64} \
    go build -trimpath -ldflags="-s -w" \
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

# server-go 只认命令行参数（唯一例外 SELFSHARE_SEAL_KEY，跨实现混跑勿设置，见 v2/README.md）：用 CMD 传参。
ENTRYPOINT ["/usr/local/bin/selfshare-server"]
CMD ["--root", "/data", "--host", "0.0.0.0", "--port", "8484"]
