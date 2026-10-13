package openapi

import "embed"

//go:embed control.openapi.yaml
var spec embed.FS

func Spec() ([]byte, error) { return spec.ReadFile("control.openapi.yaml") }
