"""Small authenticated concurrency smoke test for a deployed VMS instance."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--username", default="operations")
    parser.add_argument("--password", default="ChangeMe123!")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    csrf = json.loads(opener.open(f"{args.base_url}/api/auth/csrf/", timeout=10).read())["csrfToken"]
    login = Request(
        f"{args.base_url}/api/auth/login/",
        data=json.dumps({"username": args.username, "password": args.password}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
    )
    opener.open(login, timeout=10).read()
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in jar)

    def request_once(_index):
        started = time.perf_counter()
        try:
            with urlopen(
                Request(
                    f"{args.base_url}/api/dashboard/",
                    headers={"Cookie": cookie_header, "Accept": "application/json"},
                ),
                timeout=15,
            ) as response:
                response.read()
                return response.status, (time.perf_counter() - started) * 1000
        except HTTPError as exc:
            return exc.code, (time.perf_counter() - started) * 1000
        except Exception as exc:
            return type(exc).__name__, (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(request_once, range(args.requests)))
    status_counts = Counter(str(status) for status, _latency in results)
    failures = sum(status != 200 for status, _latency in results)
    latencies = sorted(latency for _status, latency in results)
    percentile_95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    print(
        json.dumps(
            {
                "requests": args.requests,
                "concurrency": args.concurrency,
                "failures": failures,
                "statuses": dict(sorted(status_counts.items())),
                "p50_ms": round(latencies[len(latencies) // 2], 2),
                "p95_ms": round(percentile_95, 2),
            }
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
