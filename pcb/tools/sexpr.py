"""Minimal S-expression reader and writer for KiCad files."""


class Q(str):
    """A quoted string atom."""


def parse(text):
    """Parse KiCad S-expression text into nested lists of str / Q."""
    stack, cur, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            stack.append(cur)
            cur = []
            i += 1
        elif c == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                    buf.append({"n": "\n", "t": "\t"}.get(text[j], text[j]))
                else:
                    buf.append(text[j])
                j += 1
            cur.append(Q("".join(buf)))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            cur.append(text[i:j])
            i = j
    return cur


def dump(node, indent=0):
    """Serialize a node; short lists stay on one line."""
    if isinstance(node, Q):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return fmt(node)
    parts = [dump(x, indent + 1) for x in node]
    flat = "(" + " ".join(parts) + ")"
    if len(flat) <= 100 and "\n" not in flat:
        return flat
    pad = "\t" * (indent + 1)
    return "(" + parts[0] + "".join("\n" + pad + p for p in parts[1:]) + "\n" + "\t" * indent + ")"


def fmt(v):
    """Format a coordinate the way KiCad does (no trailing zeros)."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(node, key):
    """First child list whose head is key."""
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def find_all(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]
