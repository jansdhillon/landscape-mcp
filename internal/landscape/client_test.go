package landscape

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func newTestClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return &Client{
		baseURL:    srv.URL + "/",
		accessKey:  "test-key",
		secretKey:  "test-secret",
		httpClient: &http.Client{Timeout: 5 * time.Second},
	}
}

func TestLoginMissingCredentials(t *testing.T) {
	c := &Client{baseURL: "http://unused/", httpClient: &http.Client{}}
	_, err := c.Login(context.Background())
	if err == nil {
		t.Fatal("expected error for missing credentials")
	}
	for _, name := range []string{"LANDSCAPE_API_KEY", "LANDSCAPE_API_SECRET"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error %q should name %s", err, name)
		}
	}
}

func TestLoginSuccess(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/login/access-key" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("failed to decode login body: %v", err)
		}
		if body["access_key"] != "test-key" || body["secret_key"] != "test-secret" {
			t.Errorf("unexpected login body: %v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"token": "jwt-123", "email": "admin@example.com"})
	}))

	res, err := c.Login(context.Background())
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}
	if res.Token != "jwt-123" || res.Email != "admin@example.com" {
		t.Errorf("unexpected login result: %+v", res)
	}
}

func TestLoginAuthFailure(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"message": "unauthorized"}`, http.StatusUnauthorized)
	}))

	_, err := c.Login(context.Background())
	if err == nil {
		t.Fatal("expected error for rejected credentials")
	}
	if !strings.Contains(err.Error(), "authentication failed") {
		t.Errorf("error should indicate authentication failure, got: %v", err)
	}
}

func TestLegacyRequestShape(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login/access-key":
			json.NewEncoder(w).Encode(map[string]string{"token": "jwt-123", "email": "a@b.c"})
		case "/":
			if r.Method != http.MethodPost {
				t.Errorf("legacy API must use POST, got %s", r.Method)
			}
			q := r.URL.Query()
			if q.Get("action") != "GetAccounts" {
				t.Errorf("missing action param, got query %s", r.URL.RawQuery)
			}
			if q.Get("version") != LegacyAPIVersion {
				t.Errorf("missing version param, got query %s", r.URL.RawQuery)
			}
			if q.Get("email") != "admin@example.com" {
				t.Errorf("missing custom param, got query %s", r.URL.RawQuery)
			}
			if r.Header.Get("Authorization") != "Bearer jwt-123" {
				t.Errorf("missing bearer token, got %q", r.Header.Get("Authorization"))
			}
			w.Write([]byte(`[{"account": "acme"}]`))
		default:
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
	}))

	data, err := c.Legacy(context.Background(), "GetAccounts", map[string]string{"email": "admin@example.com"})
	if err != nil {
		t.Fatalf("Legacy failed: %v", err)
	}
	if !strings.Contains(string(data), "acme") {
		t.Errorf("unexpected response: %s", data)
	}
}

func TestListComputersRequestShape(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/login/access-key":
			if r.Method != http.MethodPost {
				t.Errorf("login must use POST, got %s", r.Method)
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]string{"token": "jwt-123", "email": "a@b.c"})
		case "/api/computers":
			if r.Method != http.MethodGet {
				t.Errorf("expected GET, got %s", r.Method)
			}
			if r.Header.Get("Authorization") != "Bearer jwt-123" {
				t.Errorf("missing bearer token, got %q", r.Header.Get("Authorization"))
			}
			w.Write([]byte(`{"count": 0, "results": []}`))
		default:
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
	}))

	data, err := c.ListComputers(context.Background())
	if err != nil {
		t.Fatalf("ListComputers failed: %v", err)
	}
	if !strings.Contains(string(data), "results") {
		t.Errorf("unexpected response: %s", data)
	}
}

func TestListComputersUpstreamError(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/login/access-key" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]string{"token": "jwt-123"})
			return
		}
		http.Error(w, "boom", http.StatusInternalServerError)
	}))

	_, err := c.ListComputers(context.Background())
	if err == nil {
		t.Fatal("expected error for upstream failure")
	}
	if !strings.Contains(err.Error(), "500") {
		t.Errorf("error should include status, got: %v", err)
	}
}

func TestListComputersMissingCredentials(t *testing.T) {
	c := &Client{baseURL: "http://unused/", httpClient: &http.Client{}}
	_, err := c.ListComputers(context.Background())
	if err == nil || !strings.Contains(err.Error(), "LANDSCAPE_API_KEY") {
		t.Errorf("expected config error, got %v", err)
	}
}
