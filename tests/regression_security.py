"""Regression tests for all security findings (F-02 through F-16)."""
import asyncio
import json
import os
import subprocess
import sys

import httpx

TOKEN = "Pjpk90OYObMJmCuodoU-uUadf06rpR24n9Coqatbb-g"
DEV = "http://localhost:8099"
PROD = "http://localhost:8100"
TEMPLATE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results = {}


def test(name, passed, detail=""):
    results[name] = passed
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))


def main():
    print("=" * 70)
    print("REGRESSION TEST SUITE - Security Findings")
    print("=" * 70)

    with httpx.Client(timeout=10) as client:
        # ── F-02: Rate limit bypass ──────────────────────────────────
        print("\n[F-02] Rate Limit Bypass via X-Forwarded-For")
        for _ in range(61):
            client.post(
                f"{DEV}/api/example/echo",
                headers={"Content-Type": "application/json"},
                json={"message": "x"},
            )
        r = client.post(
            f"{DEV}/api/example/echo",
            headers={"Content-Type": "application/json", "X-Forwarded-For": "99.99.99.99"},
            json={"message": "x"},
        )
        test("XFF bypass blocked", r.status_code == 429, f"status={r.status_code}")

        # ── F-07: Security headers ───────────────────────────────────
        print("\n[F-07] Security Headers (Production)")
        r = client.get(f"{PROD}/health")
        h = r.headers
        test("X-Content-Type-Options: nosniff", h.get("x-content-type-options") == "nosniff")
        test("X-Frame-Options: DENY", h.get("x-frame-options") == "DENY")
        test("Cache-Control: no-store", "no-store" in h.get("cache-control", ""))
        test("Referrer-Policy", "strict-origin" in h.get("referrer-policy", ""))
        test("Permissions-Policy", "camera=()" in h.get("permissions-policy", ""))

        # ── F-12: Scheme logic ───────────────────────────────────────
        print("\n[F-12] Scheme Logic (subprocess unit test)")
        code = (
            "import sys; sys.path.insert(0, '.');\n"
            "from app.devices import Device;\n"
            "d1 = Device(id='x', name='x', host='fw.local',"
            " port=8443, use_tls=True, verify_ssl=False);\n"
            "d2 = Device(id='x', name='x', host='fw.local', port=80, use_tls=False);\n"
            "d3 = Device(id='x', name='x', host='fw.local', port=8443, verify_ssl=False);\n"
            "assert d1.base_url == 'https://fw.local:8443', d1.base_url;\n"
            "assert d2.base_url == 'http://fw.local:80', d2.base_url;\n"
            "assert d3.base_url == 'https://fw.local:8443', d3.base_url;\n"
            "print('OK')"
        )
        r = subprocess.run(
            [sys.executable, "-c", code],
            cwd=TEMPLATE,
            env={**os.environ, "ENV": "test"},
            capture_output=True,
            text=True,
        )
        test("Scheme logic fixed", r.returncode == 0, r.stdout.strip() or r.stderr.strip()[:80])

        # ── F-13: /metrics protegido por token ───────────────────────
        print("\n[F-13] /metrics Requires Token")
        r = client.get(f"{PROD}/metrics")
        test("/metrics rejected without auth", r.status_code == 401, f"status={r.status_code}")
        r = client.get(f"{PROD}/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
        test("/metrics accessible with token", r.status_code == 200, f"status={r.status_code}")
        test("/metrics has prometheus data", "mcp_calls_total" in r.text)

        # ── F-14: kwargs filtered ────────────────────────────────────
        print("\n[F-14] Kwargs Passthrough Filtered")
        code = (
            "import sys; sys.path.insert(0, '.');\n"
            "from app.services._http import _ALLOWED_REQUEST_KW;\n"
            "assert 'headers' not in _ALLOWED_REQUEST_KW;\n"
            "assert 'auth' not in _ALLOWED_REQUEST_KW;\n"
            "assert 'json' in _ALLOWED_REQUEST_KW;\n"
            "print('OK')"
        )
        r = subprocess.run(
            [sys.executable, "-c", code],
            cwd=TEMPLATE,
            env={**os.environ, "ENV": "test"},
            capture_output=True,
            text=True,
        )
        test("Dangerous kwargs blocked", r.returncode == 0, r.stdout.strip() or r.stderr[:80])

        # ── F-15: Token entropy ──────────────────────────────────────
        print("\n[F-15] Token Minimum Entropy")
        r_short = subprocess.run(
            [sys.executable, "-c", "import app.auth"],
            cwd=TEMPLATE,
            env={**os.environ, "ENV": "production", "API_TOKEN": "short"},
            capture_output=True,
            text=True,
        )
        test("Short token (5 chars) rejected at startup", r_short.returncode != 0)

        r_ok = subprocess.run(
            [sys.executable, "-c", "import app.auth"],
            cwd=TEMPLATE,
            env={**os.environ, "ENV": "production", "API_TOKEN": "a" * 16},
            capture_output=True,
            text=True,
        )
        test("16-char token accepted", r_ok.returncode == 0)

    # ── F-10: Path traversal via MCP ─────────────────────────────────
    print("\n[F-10] Path Traversal via MCP (Production)")
    asyncio.run(_test_f10())

    # ── Summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    total = len(results)
    print(f"RESULTS: {passed}/{total} PASSED | {failed} FAILED")
    if failed:
        print(f"FAILED: {[k for k, v in results.items() if not v]}")
    else:
        print("ALL FIXES VERIFIED SUCCESSFULLY")
    print("=" * 70)
    sys.exit(0 if failed == 0 else 1)


async def _test_f10():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {TOKEN}",
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        # Initialize MCP session
        init = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "regtest"},
            },
        }
        r = await c.post(f"{PROD}/mcp", headers=headers, json=init)
        sid = r.headers.get("mcp-session-id", "")
        if not sid:
            test("MCP session created", False, f"status={r.status_code}")
            return

        headers["Mcp-Session-Id"] = sid
        await c.post(
            f"{PROD}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        # Test path traversal payload
        call = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 10,
            "params": {
                "name": "deactivate_resource",
                "arguments": {"device_id": "test-fw-01", "resource_id": "../../admin/reboot"},
            },
        }
        r = await c.post(f"{PROD}/mcp", headers=headers, json=call)

        for line in r.text.strip().split("\n"):
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                content = data.get("result", {}).get("content", [])
                if content:
                    text = content[0].get("text", "")
                    try:
                        obj = json.loads(text)
                        blocked = obj.get("erro") and "inv" in obj.get("mensagem", "").lower()
                        test(
                            "Traversal ../../admin/reboot REJECTED",
                            blocked,
                            obj.get("mensagem", "")[:60],
                        )
                    except (json.JSONDecodeError, ValueError):
                        test("Traversal rejected", False, text[:80])
                break
        else:
            test("Traversal rejected (parse)", False, r.text[:100])

        # Test legitimate resource_id still works
        call2 = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 11,
            "params": {
                "name": "deactivate_resource",
                "arguments": {"device_id": "test-fw-01", "resource_id": "res_123"},
            },
        }
        try:
            r = await c.post(f"{PROD}/mcp", headers=headers, json=call2)
            for line in r.text.strip().split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    content = data.get("result", {}).get("content", [])
                    if content:
                        text = content[0].get("text", "")
                        obj = json.loads(text)
                        not_validation_err = "inv" not in obj.get("mensagem", "").lower()
                        test(
                            "Legit res_123 NOT rejected",
                            not_validation_err,
                            obj.get("mensagem", "")[:60],
                        )
                    break
        except httpx.ReadTimeout:
            test("Legit res_123 NOT rejected", True, "timeout=upstream unreachable (accepted)")


if __name__ == "__main__":
    main()
