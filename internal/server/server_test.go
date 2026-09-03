package server

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/jansdhillon/landscape-mcp/internal/landscape"
)

type stubClient struct {
	loginResult *landscape.LoginResult
	loginErr    error
	legacyData  json.RawMessage
	legacyErr   error
	restData    json.RawMessage
	restErr     error

	legacyAction string
	legacyParams map[string]string
}

func (s *stubClient) Login(ctx context.Context) (*landscape.LoginResult, error) {
	return s.loginResult, s.loginErr
}

func (s *stubClient) Legacy(ctx context.Context, action string, params map[string]string) (json.RawMessage, error) {
	s.legacyAction = action
	s.legacyParams = params
	return s.legacyData, s.legacyErr
}

func (s *stubClient) ListComputers(ctx context.Context) (json.RawMessage, error) {
	return s.restData, s.restErr
}

func resultText(t *testing.T, res *mcp.CallToolResult) string {
	t.Helper()
	if res == nil || len(res.Content) == 0 {
		t.Fatal("empty result")
	}
	tc, ok := res.Content[0].(*mcp.TextContent)
	if !ok {
		t.Fatalf("expected text content, got %T", res.Content[0])
	}
	return tc.Text
}

func TestGetAccountsNoFilter(t *testing.T) {
	stub := &stubClient{legacyData: json.RawMessage(`[{"account":"acme"}]`)}
	s := New(stub)

	res, _, err := s.GetAccounts(context.Background(), nil, GetAccountsParams{})
	if err != nil {
		t.Fatalf("GetAccounts failed: %v", err)
	}
	if stub.legacyAction != "GetAccounts" {
		t.Errorf("wrong action: %s", stub.legacyAction)
	}
	if len(stub.legacyParams) != 0 {
		t.Errorf("expected no params, got %v", stub.legacyParams)
	}
	if !strings.Contains(resultText(t, res), "acme") {
		t.Errorf("result missing account: %s", resultText(t, res))
	}
}

func TestGetAccountsEmailFilter(t *testing.T) {
	stub := &stubClient{legacyData: json.RawMessage(`[]`)}
	s := New(stub)

	_, _, err := s.GetAccounts(context.Background(), nil, GetAccountsParams{Email: "a@b.c"})
	if err != nil {
		t.Fatalf("GetAccounts failed: %v", err)
	}
	if stub.legacyParams["email"] != "a@b.c" {
		t.Errorf("expected email param, got %v", stub.legacyParams)
	}
}

func TestGetAccountsErrorPropagates(t *testing.T) {
	stub := &stubClient{legacyErr: errors.New("missing required environment variables: LANDSCAPE_API_KEY")}
	s := New(stub)

	_, _, err := s.GetAccounts(context.Background(), nil, GetAccountsParams{})
	if err == nil || !strings.Contains(err.Error(), "LANDSCAPE_API_KEY") {
		t.Errorf("expected config error, got %v", err)
	}
}

func TestGetLicensesSingleAccount(t *testing.T) {
	stub := &stubClient{
		legacyData: json.RawMessage(`[{"account":"acme","licenses":[{"id":1}]}]`),
	}
	s := New(stub)

	res, _, err := s.GetLicenses(context.Background(), nil, GetLicensesParams{AccountName: "acme"})
	if err != nil {
		t.Fatalf("GetLicenses failed: %v", err)
	}
	if stub.legacyParams["account_name"] != "acme" {
		t.Errorf("expected account_name param, got %v", stub.legacyParams)
	}
	text := resultText(t, res)
	if !strings.Contains(text, `"id": 1`) {
		t.Errorf("expected indented license JSON, got: %s", text)
	}
}

func TestGetLicensesAllAccounts(t *testing.T) {
	stub := &stubClient{
		loginResult: &landscape.LoginResult{Token: "t", Email: "admin@example.com"},
		legacyData: json.RawMessage(`[
			{"account":"acme","licenses":[{"id":1}]},
			{"account":"globex","licenses":[{"id":2},{"id":3}]}
		]`),
	}
	s := New(stub)

	res, _, err := s.GetLicenses(context.Background(), nil, GetLicensesParams{})
	if err != nil {
		t.Fatalf("GetLicenses failed: %v", err)
	}
	if stub.legacyParams["email"] != "admin@example.com" {
		t.Errorf("expected email filter from login, got %v", stub.legacyParams)
	}
	var merged []map[string]any
	if err := json.Unmarshal([]byte(resultText(t, res)), &merged); err != nil {
		t.Fatalf("result not valid JSON: %v", err)
	}
	if len(merged) != 3 {
		t.Fatalf("expected 3 merged licenses, got %d", len(merged))
	}
	if merged[0]["account"] != "acme" || merged[2]["account"] != "globex" {
		t.Errorf("licenses not annotated with account: %v", merged)
	}
}

func TestGetComputers(t *testing.T) {
	stub := &stubClient{restData: json.RawMessage(`{"results":[{"id":1,"hostname":"web-1"}]}`)}
	s := New(stub)

	res, _, err := s.GetComputers(context.Background(), nil, GetComputersParams{})
	if err != nil {
		t.Fatalf("GetComputers failed: %v", err)
	}
	if !strings.Contains(resultText(t, res), "web-1") {
		t.Errorf("result missing computer: %s", resultText(t, res))
	}
}

func TestGetComputersErrorPropagates(t *testing.T) {
	stub := &stubClient{restErr: errors.New("API request failed: 500")}
	s := New(stub)

	_, _, err := s.GetComputers(context.Background(), nil, GetComputersParams{})
	if err == nil || !strings.Contains(err.Error(), "500") {
		t.Errorf("expected upstream error, got %v", err)
	}
}

func TestAuditAccountPrompt(t *testing.T) {
	s := New(&stubClient{})
	res, err := s.AuditAccount(context.Background(), &mcp.GetPromptRequest{
		Params: &mcp.GetPromptParams{
			Arguments: map[string]string{"account_name": "acme"},
		},
	})
	if err != nil {
		t.Fatalf("AuditAccount failed: %v", err)
	}
	if len(res.Messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(res.Messages))
	}
	text := res.Messages[0].Content.(*mcp.TextContent).Text
	for _, want := range []string{"acme", "licenses", "Ubuntu Pro", "7 days"} {
		if !strings.Contains(text, want) {
			t.Errorf("prompt missing %q: %s", want, text)
		}
	}
}
