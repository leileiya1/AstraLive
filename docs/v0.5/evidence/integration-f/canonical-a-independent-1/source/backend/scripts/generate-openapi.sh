#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p generated/openapi generated/runtimeapi
# Keep the embedded validation document byte-for-byte identical to the frozen source.
cp ../contracts/control-api.openapi.yaml generated/openapi/control.openapi.yaml
go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.5.1 -generate types -package openapi -o generated/openapi/control.gen.go ../contracts/control-api.openapi.yaml
go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.5.1 -generate types -package runtimeapi -o generated/runtimeapi/runtime.gen.go ../contracts/runtime-api.openapi.yaml
