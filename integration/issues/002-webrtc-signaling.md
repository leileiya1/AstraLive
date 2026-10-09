# ISSUE-002: WebRTC 曾缺少信令契约（v1.0，已解决）

- Severity: P1（历史）
- Module: backend / runtime / frontend
- Reproduction: v1.0 浏览器无公共 SDP offer/answer 路由。
- Expected: Browser 完整 ICE offer 经 Go 转发 Runtime，收到完整 answer，媒体由 Browser 直连 Runtime。
- Actual: v1.0 无路由；Contract v1.1 和三端 Migration 已修复。2026-10-06 HTTP 集成测试观察到 Go 转发 Runtime，真实 headless Chrome 已连接并收到 audio/video tracks。跨主机 ICE 可达性仍待部署验证。
- Contract Reference: `contracts/CONTRACTS.md` §7.6、§8.7。
- Suggested Fix: 无；保留作历史记录。
