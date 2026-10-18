// Offline test driver. Not a server or production route.
package main

import (
	"astralive/backend/internal/durablelivev2/wire"
	"bufio"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
)

type Case struct {
	Schema, Body, Mode, Operation, Role, Target, Method, Route string
	Status                                                     int
}
type Result struct {
	OK                                      bool
	Body, Error, Diagnostic, Schema, Digest string
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 32*1024*1024)
	encoder := json.NewEncoder(os.Stdout)
	for scanner.Scan() {
		var c Case
		var out Result
		if json.Unmarshal(scanner.Bytes(), &c) != nil {
			panic("invalid test case")
		}
		raw, e := base64.StdEncoding.DecodeString(c.Body)
		if e != nil {
			panic("invalid test encoding")
		}
		var msg wire.Message
		var b []byte
		switch c.Mode {
		case "artifact":
			var artifact *wire.AnswerArtifact
			artifact, e = wire.DecodeAnswerArtifact(raw)
			if e == nil {
				e = wire.VerifyAnswerArtifactHashes(artifact)
				msg = artifact
			}
		case "canonical":
			b, e = wire.CanonicalJSON(raw)
			if e == nil {
				out.Digest, e = wire.DigestJSON(raw)
			}
		case "request":
			msg, e = wire.DecodeRequest(wire.OperationID(c.Operation), wire.RequestContext{Role: wire.Role(c.Role), Target: wire.Target(c.Target), Method: c.Method, RouteTemplate: c.Route}, raw)
		case "response":
			msg, e = wire.DecodeResponse(wire.OperationID(c.Operation), c.Status, raw)
		default:
			msg, e = wire.Decode(c.Schema, raw)
		}
		if e == nil && msg != nil {
			if c.Mode == "request" {
				b, e = wire.EncodeRequest(wire.OperationID(c.Operation), wire.RequestContext{Role: wire.Role(c.Role), Target: wire.Target(c.Target), Method: c.Method, RouteTemplate: c.Route}, msg)
			} else if c.Mode == "response" {
				b, e = wire.EncodeResponse(wire.OperationID(c.Operation), c.Status, msg)
			} else {
				b, e = wire.Encode(msg)
			}
			out.Schema = msg.SchemaName()
			out.Diagnostic = fmt.Sprintf("%v|%+v|%#v|%s|%q", msg, msg, msg, msg, msg)
		}
		if e == nil {
			out.OK = true
			out.Body = base64.StdEncoding.EncodeToString(b)
		} else {
			out.Error = e.Error()
		}
		if e = encoder.Encode(out); e != nil {
			panic("test output failed")
		}
	}
	if scanner.Err() != nil {
		panic("test input failed")
	}
}
