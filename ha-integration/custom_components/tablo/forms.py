"""Lists edited as text in the options forms: one entry per line, fields split by "|" (§8.3).

Pure functions, so the round trip config -> text -> config is tested without HA.
"""

from __future__ import annotations

SECURITY = ("WPA", "WEP", "nopass")


class FormError(ValueError):
    """A line that cannot be read; the message names the line."""


def _lines(text: str) -> list[tuple[int, list[str]]]:
    result = []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            result.append((n, [p.strip() for p in line.split("|")]))
    return result


# --- Wi-Fi networks: "SSID | password | WPA | hidden" ------------------------

def wifi_to_text(networks: list[dict]) -> str:
    lines = []
    for w in networks:
        parts = [w["ssid"], w.get("password", ""), w.get("security", "WPA")]
        if w.get("hidden"):
            parts.append("hidden")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def wifi_from_text(text: str) -> list[dict]:
    result = []
    for n, parts in _lines(text):
        if not 1 <= len(parts) <= 4 or not parts[0]:
            raise FormError(f"line {n}: expected 'SSID | password | WPA | hidden'")
        parts += [""] * (4 - len(parts))
        ssid, password, security, hidden = parts
        security = security or ("WPA" if password else "nopass")
        match = next((s for s in SECURITY if s.casefold() == security.casefold()), None)
        if match is None:
            raise FormError(f"line {n}: security is one of {', '.join(SECURITY)}")
        if hidden not in ("", "hidden"):
            raise FormError(f"line {n}: the last field is 'hidden' or empty")
        result.append({"ssid": ssid, "password": password, "security": match, "hidden": hidden == "hidden"})
    if len({w["ssid"] for w in result}) != len(result):
        raise FormError("the same network twice")
    return result


# --- Home block rows: "label | template" (§8.3) --------------------------------

HOME_ROWS_MAX = 5  # rows that fit the block


def home_rows_to_text(rows: list[dict]) -> str:
    return "\n".join(f"{r['label']} | {r['template']}" if r.get("label") else f"| {r['template']}" for r in rows)


def home_rows_from_text(text: str) -> list[dict]:
    """The label is what comes before the first "|", unless that part is already template (has "{"):
    templates use "|" for filters, labels never have braces."""
    result = []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, template = "", line
        head, sep, tail = line.partition("|")
        if sep and "{" not in head:
            label, template = head.strip(), tail.strip()
        if not template:
            raise FormError(f"line {n}: expected 'label | template'")
        result.append({"label": label, "template": template})
    if len(result) > HOME_ROWS_MAX:
        raise FormError(f"at most {HOME_ROWS_MAX} rows fit the Home block")
    return result
