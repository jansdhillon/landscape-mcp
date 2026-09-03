// Command landscape-mcp runs an MCP server over stdio exposing the
// Landscape API to AI agents.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/jansdhillon/landscape-mcp/internal/landscape"
	"github.com/jansdhillon/landscape-mcp/internal/server"
)

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	// Logs go to stderr only; on stdio, stdout carries the protocol.
	log.SetPrefix("landscape-mcp: ")

	transport := flag.String("transport", envOr("LANDSCAPE_MCP_TRANSPORT", "stdio"),
		"transport to serve: stdio or http (env LANDSCAPE_MCP_TRANSPORT)")
	addr := flag.String("addr", envOr("LANDSCAPE_MCP_HTTP_ADDR", ":8080"),
		"listen address for the http transport (env LANDSCAPE_MCP_HTTP_ADDR)")
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	mcpServer := mcp.NewServer(&mcp.Implementation{
		Name:    "landscape-api",
		Version: "v1.0.0",
	}, nil)

	server.New(landscape.NewClientFromEnv()).Register(mcpServer)

	switch *transport {
	case "stdio":
		log.Printf("starting MCP server over stdio")
		if err := mcpServer.Run(ctx, &mcp.StdioTransport{}); err != nil {
			log.Fatalf("server failed: %v", err)
		}
	case "http":
		handler := mcp.NewStreamableHTTPHandler(func(r *http.Request) *mcp.Server {
			return mcpServer
		}, nil)
		mux := http.NewServeMux()
		mux.Handle("/mcp", handler)
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			fmt.Fprintln(w, "ok")
		})
		httpServer := &http.Server{Addr: *addr, Handler: mux}

		go func() {
			<-ctx.Done()
			httpServer.Shutdown(context.Background())
		}()

		log.Printf("starting MCP server over streamable HTTP at %s/mcp", *addr)
		if err := httpServer.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("server failed: %v", err)
		}
	default:
		log.Fatalf("unknown transport %q: must be stdio or http", *transport)
	}
}
