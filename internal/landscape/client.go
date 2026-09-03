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
	"sync"
	"time"

	apiclient "github.com/jansdhillon/landscape-go-api-client/client"
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

// Client talks to a Landscape server. Legacy API actions go through the
// hand-rolled shim (the legacy API is not OpenAPI-specifiable); v2 calls go
// through the generated landscape-go-api-client, built lazily on first use.
type Client struct {
	baseURL    string
	accessKey  string
	secretKey  string
	httpClient *http.Client

	v2Once   sync.Once
	v2       *apiclient.ClientWithResponses
	v2Err    error
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

// v2Client lazily builds the generated v2 API client on first use, so the
// server can start without credentials (errors surface per call instead).
// The wrapper logs in once at construction and reuses the JWT.
func (c *Client) v2Client(ctx context.Context) (*apiclient.ClientWithResponses, error) {
	c.v2Once.Do(func() {
		if err := c.missingCredentials(); err != nil {
			c.v2Err = err
			return
		}
		// The generated client prepends spec server URLs that already
		// include the "/api" path prefix.
		rootURL := strings.TrimSuffix(strings.TrimSuffix(c.baseURL, "/"), "/api")
		provider := &apiclient.AccessKeyProvider{
			AccessKey: c.accessKey,
			SecretKey: c.secretKey,
		}
		client, err := apiclient.NewLandscapeAPIClient(
			rootURL,
			provider,
			apiclient.WithHTTPClient(c.httpClient),
		)
		if err != nil {
			c.v2Err = fmt.Errorf("failed to initialize v2 API client: %w", err)
			return
		}
		c.v2 = client
	})
	return c.v2, c.v2Err
}

// ListComputers returns the raw body of GET /api/computers via the generated
// v2 client. The response is passed through unmodified for output parity with
// the previous implementation; typed handling comes when the tool grows
// filters.
func (c *Client) ListComputers(ctx context.Context) (json.RawMessage, error) {
	v2, err := c.v2Client(ctx)
	if err != nil {
		return nil, err
	}

	res, err := v2.ListComputers(ctx, &apiclient.ListComputersParams{})
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
