package main

import "testing"

func TestValidateTLS(t *testing.T) {
	cases := []struct {
		name, cert, key string
		wantErr         bool
	}{
		{"neither", "", "", false},
		{"both", "c.pem", "k.pem", false},
		{"cert only", "c.pem", "", true},
		{"key only", "", "k.pem", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if err := validateTLS(c.cert, c.key); (err != nil) != c.wantErr {
				t.Fatalf("validateTLS(%q, %q) error = %v, wantErr %v", c.cert, c.key, err, c.wantErr)
			}
		})
	}
}
