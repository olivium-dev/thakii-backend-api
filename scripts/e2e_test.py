import os
import sys
import json
import time
import tempfile
import argparse
from typing import Optional, Dict, Any

import requests


def pretty(label: str, data: Any) -> None:
    try:
        print(f"{label}: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception:
        print(f"{label}: {data}")


def get_token(base_url: str, explicit_token: Optional[str]) -> Optional[str]:
    # 1) If explicit token provided, use it
    if explicit_token:
        return explicit_token.strip()

    # 2) If STATIC_BEARER_TOKEN is provided in environment, use it
    static_token = os.getenv("STATIC_BEARER_TOKEN")
    if static_token:
        return static_token.strip()

    # 3) Try to generate a test custom token if endpoint exists
    try:
        resp = requests.post(f"{base_url}/auth/test-token", timeout=20)
        if resp.status_code == 200:
            payload = resp.json()
            return payload.get("custom_token")
    except Exception:
        pass

    return None


def request_json(method: str, url: str, headers: Optional[Dict[str, str]] = None, **kwargs) -> (int, Dict[str, Any]):
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    return status, body


def run_e2e(base_url: str, token: Optional[str]) -> int:
    print("=== Backend E2E Test ===")
    print(f"Base URL: {base_url}")

    # Health
    status, body = request_json("GET", f"{base_url}/health")
    print(f"/health -> {status}")
    pretty("health", body)
    if status != 200:
        print("Health check failed; aborting.")
        return 1

    # Auth: figure token
    auth_token = get_token(base_url, token)
    if not auth_token:
        print("No token available (STATIC_BEARER_TOKEN not set and /auth/test-token unavailable).")
        return 2
    auth_header = {"Authorization": f"Bearer {auth_token}"}

    # /auth/user
    status, body = request_json("GET", f"{base_url}/auth/user", headers=auth_header)
    print(f"/auth/user -> {status}")
    pretty("auth_user", body)

    # /list
    status, body = request_json("GET", f"{base_url}/list", headers=auth_header)
    print(f"/list -> {status}")
    pretty("list", body)

    # /admin/videos
    status, body = request_json("GET", f"{base_url}/admin/videos", headers=auth_header)
    print(f"/admin/videos -> {status}")
    pretty("admin_videos", body)

    # /admin/stats
    status, body = request_json("GET", f"{base_url}/admin/stats", headers=auth_header)
    print(f"/admin/stats -> {status}")
    pretty("admin_stats", body)

    # OPTIONS /upload (preflight simulation)
    try:
        resp = requests.options(
            f"{base_url}/upload",
            headers={
                "Origin": "https://thakii-frontend.netlify.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            },
            timeout=20,
        )
        print(f"OPTIONS /upload -> {resp.status_code}")
    except Exception as ex:
        print(f"OPTIONS /upload error: {ex}")

    # POST /upload (small test file)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp.write(b"test content from e2e script")
            tmp.flush()
            files = {"file": (os.path.basename(tmp.name), open(tmp.name, "rb"))}
            resp = requests.post(f"{base_url}/upload", headers=auth_header, files=files, timeout=120)
            print(f"/upload -> {resp.status_code}")
            try:
                pretty("upload", resp.json())
            except Exception:
                print(resp.text)
    except Exception as ex:
        print(f"/upload error: {ex}")

    print("=== E2E Completed ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backend E2E tests")
    parser.add_argument("--base", default=os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:5001"), help="Base URL of backend")
    parser.add_argument("--token", default=os.getenv("E2E_AUTH_TOKEN"), help="Explicit bearer token to use")
    args = parser.parse_args()

    try:
        return run_e2e(args.base, args.token)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())


