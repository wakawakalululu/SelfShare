.PHONY: build build-linux build-windows build-darwin build-all test vet docker docker-run run clean

BINARY = selfshare-server
LDFLAGS = -ldflags="-s -w"

build:
	CGO_ENABLED=0 go build -trimpath $(LDFLAGS) -o bin/$(BINARY) ./cmd/selfshare-server

build-linux:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath $(LDFLAGS) -o bin/$(BINARY)-linux-amd64 ./cmd/selfshare-server
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath $(LDFLAGS) -o bin/$(BINARY)-linux-arm64 ./cmd/selfshare-server

build-windows:
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath $(LDFLAGS) -o bin/$(BINARY)-windows-amd64.exe ./cmd/selfshare-server

build-darwin:
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath $(LDFLAGS) -o bin/$(BINARY)-darwin-amd64 ./cmd/selfshare-server
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath $(LDFLAGS) -o bin/$(BINARY)-darwin-arm64 ./cmd/selfshare-server

build-all: build-linux build-windows build-darwin

test:
	go test ./...

vet:
	go vet ./...

docker:
	docker build -t selfshare-server:2 .
	docker tag selfshare-server:2 selfshare-server:latest

docker-run:
	docker run -d --name selfshare -p 8484:8484 -v selfshare-data:/data selfshare-server:latest

# 本机快速起服务（数据目录 ./data，端口 8484）
run: build
	./bin/$(BINARY) --root ./data

clean:
	rm -rf bin/
	go clean
