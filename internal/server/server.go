// Package server wires the Landscape API client to MCP tools and prompts.
package server

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/jansdhillon/landscape-mcp/internal/landscape"
)

// LandscapeClient is the subset of the Landscape API the tools need.
// *landscape.Client satisfies it; tests substitute a stub.
type LandscapeClient interface {
	Login(ctx context.Context) (*landscape.LoginResult, error)
	Legacy(ctx context.Context, action string, params map[string]string) (json.RawMessage, error)
	REST(ctx context.Context, method, endpoint string, params map[string]string) (json.RawMessage, error)
}

// Server holds the dependencies shared by the tool handlers.
type Server struct {
	client LandscapeClient
}

// New returns a Server backed by the given Landscape client.
func New(client LandscapeClient) *Server {
	return &Server{client: client}
}

func textResult(v any) (*mcp.CallToolResult, error) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("failed to encode result: %w", err)
	}
	return &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: string(data)}},
	}, nil
}

// GetAccountsParams are the inputs to the get_accounts tool.
type GetAccountsParams struct {
	Email       string `json:"email,omitempty" jsonschema:"filter accounts by email address"`
	AccountName string `json:"account_name,omitempty" jsonschema:"filter accounts by account name"`
}

// GetAccounts implements the get_accounts tool via the legacy GetAccounts action.
func (s *Server) GetAccounts(ctx context.Context, req *mcp.CallToolRequest, params GetAccountsParams) (*mcp.CallToolResult, any, error) {
	p := map[string]string{}
	if params.Email != "" {
		p["email"] = params.Email
	} else if params.AccountName != "" {
		p["account_name"] = params.AccountName
	}

	data, err := s.client.Legacy(ctx, "GetAccounts", p)
	if err != nil {
		return nil, nil, err
	}

	var v any
	if err := json.Unmarshal(data, &v); err != nil {
		return nil, nil, fmt.Errorf("failed to parse GetAccounts response: %w", err)
	}
	res, err := textResult(v)
	return res, nil, err
}

// GetLicensesParams are the inputs to the get_licenses tool.
type GetLicensesParams struct {
	AccountName string `json:"account_name,omitempty" jsonschema:"account to fetch licenses for; omit to aggregate licenses across all accessible accounts"`
}

// GetLicenses implements the get_licenses tool, preserving the Python flow:
// with account_name, return that account's licenses; otherwise look up the
// login email's accounts and merge licenses annotated with account name.
func (s *Server) GetLicenses(ctx context.Context, req *mcp.CallToolRequest, params GetLicensesParams) (*mcp.CallToolResult, any, error) {
	if params.AccountName != "" {
		data, err := s.client.Legacy(ctx, "GetAccounts", map[string]string{"account_name": params.AccountName})
		if err != nil {
			return nil, nil, err
		}
		var accounts []map[string]any
		if err := json.Unmarshal(data, &accounts); err != nil {
			return nil, nil, fmt.Errorf("failed to parse GetAccounts response: %w", err)
		}
		if len(accounts) == 0 {
			res, err := textResult(fmt.Sprintf("Unable to fetch licenses for account: %s", params.AccountName))
			return res, nil, err
		}
		licenses, _ := accounts[0]["licenses"].([]any)
		res, err := textResult(licenses)
		return res, nil, err
	}

	login, err := s.client.Login(ctx)
	if err != nil {
		return nil, nil, err
	}
	data, err := s.client.Legacy(ctx, "GetAccounts", map[string]string{"email": login.Email})
	if err != nil {
		return nil, nil, err
	}
	var accounts []map[string]any
	if err := json.Unmarshal(data, &accounts); err != nil {
		return nil, nil, fmt.Errorf("failed to parse GetAccounts response: %w", err)
	}

	all := []map[string]any{}
	for _, account := range accounts {
		name, _ := account["account"].(string)
		if name == "" {
			name = "unknown"
		}
		licenses, _ := account["licenses"].([]any)
		for _, l := range licenses {
			license, ok := l.(map[string]any)
			if !ok {
				continue
			}
			all = append(all, mergeAccount(name, license))
		}
	}
	res, err := textResult(all)
	return res, nil, err
}

func mergeAccount(name string, license map[string]any) map[string]any {
	merged := map[string]any{"account": name}
	for k, v := range license {
		merged[k] = v
	}
	return merged
}

// GetComputersParams are the inputs to the get_computers tool (none).
type GetComputersParams struct{}

// GetComputers implements the get_computers tool via REST GET /computers.
func (s *Server) GetComputers(ctx context.Context, req *mcp.CallToolRequest, params GetComputersParams) (*mcp.CallToolResult, any, error) {
	data, err := s.client.REST(ctx, "GET", "/computers", nil)
	if err != nil {
		return nil, nil, err
	}
	var v any
	if err := json.Unmarshal(data, &v); err != nil {
		return nil, nil, fmt.Errorf("failed to parse computers response: %w", err)
	}
	res, err := textResult(v)
	return res, nil, err
}

// AuditAccount implements the audit_account prompt.
func (s *Server) AuditAccount(ctx context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
	accountName := req.Params.Arguments["account_name"]
	return &mcp.GetPromptResult{
		Description: "Summarize the computers and license status of a Landscape account.",
		Messages: []*mcp.PromptMessage{
			{
				Role: "user",
				Content: &mcp.TextContent{Text: fmt.Sprintf(
					"Audit the Landscape account '%s'. "+
						"Use the available tools to: "+
						"1) fetch the account's licenses and flag any that are expired or nearly expired, "+
						"2) fetch all computers and summarise their Ubuntu Pro status, distribution versions, and any that haven't exchanged data in more than 7 days. "+
						"Present a concise report.", accountName)},
			},
		},
	}, nil
}

// Register wires all tools and prompts onto an MCP server.
func (s *Server) Register(mcpServer *mcp.Server) {
	mcp.AddTool(mcpServer, &mcp.Tool{
		Name:        "get_accounts",
		Description: "Get Landscape accounts. Optionally filter by email address or account name.",
	}, s.GetAccounts)

	mcp.AddTool(mcpServer, &mcp.Tool{
		Name:        "get_licenses",
		Description: "Get Landscape licenses by account name. Returns all licenses across all (accessible) accounts if no account name is provided.",
	}, s.GetLicenses)

	mcp.AddTool(mcpServer, &mcp.Tool{
		Name:        "get_computers",
		Description: "Get all computers registered in Landscape, including their hardware info, Ubuntu Pro status, distribution, tags, and last exchange time.",
	}, s.GetComputers)

	mcpServer.AddPrompt(&mcp.Prompt{
		Name:        "audit_account",
		Description: "Prompt to summarize the computers and license status of a Landscape account.",
		Arguments: []*mcp.PromptArgument{
			{
				Name:        "account_name",
				Description: "Name of the Landscape account to audit",
				Required:    true,
			},
		},
	}, s.AuditAccount)
}
