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


# --- grade sheets: "url | label" ----------------------------------------------

def sheets_to_text(sheets: list[dict]) -> str:
    return "\n".join(f"{s['url']} | {s['label']}" if s.get("label") else s["url"] for s in sheets)


def sheets_from_text(text: str) -> list[dict]:
    result = []
    for n, parts in _lines(text):
        if len(parts) > 2 or not parts[0].startswith("http"):
            raise FormError(f"line {n}: expected 'link | label'")
        sheet = {"url": parts[0]}
        if len(parts) == 2 and parts[1]:
            sheet["label"] = parts[1]
        result.append(sheet)
    return result


# --- Telegram channels: "@name" or "@name study" -------------------------------

def channels_to_text(channels: list[dict | str]) -> str:
    lines = []
    for c in channels:
        c = {"name": c} if isinstance(c, str) else c
        lines.append(f"@{c['name']} study" if c.get("study") else f"@{c['name']}")
    return "\n".join(lines)


def channels_from_text(text: str) -> list[dict]:
    result = []
    for n, line in enumerate((text or "").splitlines(), 1):
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        study = words[1:] == ["study"]
        if len(words) > 1 and not study:
            raise FormError(f"line {n}: expected '@channel' or '@channel study'")
        name = words[0].rstrip("/").rsplit("/", 1)[-1].lstrip("@")
        if not name:
            raise FormError(f"line {n}: empty channel name")
        result.append({"name": name, "study": study})
    if len({c["name"].casefold() for c in result}) != len(result):
        raise FormError("the same channel twice")
    return result


# --- subject names: "name as in the source | English title | Abbr" -----------

def subjects_to_text(subjects: list[dict]) -> str:
    return "\n".join(f"{s['name']} | {s['title']} | {s['abbr']}" for s in subjects)


def subjects_from_text(text: str) -> list[dict]:
    result = []
    for n, parts in _lines(text):
        if len(parts) != 3 or not all(parts):
            raise FormError(f"line {n}: expected 'name | English title | Abbr'")
        result.append({"name": parts[0], "title": parts[1], "abbr": parts[2]})
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
