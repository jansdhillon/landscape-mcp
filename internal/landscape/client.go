// Package landscape provides a client for the Landscape API, covering
// access-key login, the legacy query-param API, and the REST v2 API.
package landscape

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	// DefaultBaseURL is used when LANDSCAPE_API_URI is unset.
	DefaultBaseURL = "https://landscape.canonical.com/api/"
	// LegacyAPIVersion pins the legacy API version, matching the Python server.
	LegacyAPIVersion = "2011-08-01"

	envAPIKey    = "LANDSCAPE_API_KEY"
	envAPISecret = "LANDSCAPE_API_SECRET"
	envAPIURI    = "LANDSCAPE_API_URI"
)

// Client talks to a Landscape server.
type Client struct {
	baseURL    string
	accessKey  string
	secretKey  string
	httpClient *http.Client
}

// LoginResult holds the outcome of an access-key login.
type LoginResult struct {
	Token string
	Email string
}

// NewClientFromEnv builds a Client from the LANDSCAPE_API_KEY,
// LANDSCAPE_API_SECRET, and LANDSCAPE_API_URI environment variables.
// Missing credentials are reported lazily by Login, so the server can
// start and list tools without credentials configured.
func NewClientFromEnv() *Client {
	baseURL := os.Getenv(envAPIURI)
	if baseURL == "" {
		baseURL = DefaultBaseURL
	}
	return &Client{
		baseURL:   strings.TrimSuffix(baseURL, "/") + "/",
		accessKey: os.Getenv(envAPIKey),
		secretKey: os.Getenv(envAPISecret),
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *Client) missingCredentials() error {
	var missing []string
	if c.accessKey == "" {
		missing = append(missing, envAPIKey)
	}
	if c.secretKey == "" {
		missing = append(missing, envAPISecret)
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required environment variables: %s", strings.Join(missing, ", "))
	}
	return nil
}

// Login authenticates with the access and secret keys and returns a JWT.
func (c *Client) Login(ctx context.Context) (*LoginResult, error) {
	if err := c.missingCredentials(); err != nil {
		return nil, err
	}

	body, err := json.Marshal(map[string]string{
		"access_key": c.accessKey,
		"secret_key": c.secretKey,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to encode login request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"login/access-key", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to build login request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	res, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to get access token: %w", err)
	}
	defer res.Body.Close()

	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("authentication failed: %s", res.Status)
	}

	var data struct {
		Token string `json:"token"`
		Email string `json:"email"`
	}
	if err := json.NewDecoder(res.Body).Decode(&data); err != nil {
		return nil, fmt.Errorf("failed to decode login response: %w", err)
	}
	if data.Token == "" {
		return nil, fmt.Errorf("authentication failed: no token in login response")
	}
	return &LoginResult{Token: data.Token, Email: data.Email}, nil
}

// Legacy calls the legacy API: POST {base}?action=<action>&version=2011-08-01
// with any extra params in the query string, matching the Python server.
func (c *Client) Legacy(ctx context.Context, action string, params map[string]string) (json.RawMessage, error) {
	login, err := c.Login(ctx)
	if err != nil {
		return nil, err
	}

	q := url.Values{"action": {action}, "version": {LegacyAPIVersion}}
	for k, v := range params {
		q.Set(k, v)
	}
	u := strings.TrimSuffix(c.baseURL, "/") + "?" + q.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+login.Token)

	return c.do(req)
}

// REST calls the REST v2 API: <method> {base}/<endpoint> with params in the
// query string.
func (c *Client) REST(ctx context.Context, method, endpoint string, params map[string]string) (json.RawMessage, error) {
	login, err := c.Login(ctx)
	if err != nil {
		return nil, err
	}

	u, err := url.Parse(c.baseURL + strings.TrimPrefix(endpoint, "/"))
	if err != nil {
		return nil, fmt.Errorf("failed to build request URL: %w", err)
	}
	q := u.Query()
	for k, v := range params {
		q.Set(k, v)
	}
	u.RawQuery = q.Encode()

	req, err := http.NewRequestWithContext(ctx, method, u.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("failed to build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+login.Token)

	return c.do(req)
}

func (c *Client) do(req *http.Request) (json.RawMessage, error) {
	res, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("API request failed: %w", err)
	}
	defer res.Body.Close()

	data, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read API response: %w", err)
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("API request failed: %s", res.Status)
	}
	return json.RawMessage(data), nil
}
