# PlatformIO pre-script: patch arduinoWebSockets for 48 KB frames (§3.2).
# 1. The library defines WEBSOCKETS_MAX_DATA_SIZE without #ifndef, so -D cannot override it,
#    and a frame is one 48 020-byte message: lift the 15 KB limit.
# 2. A received message's buffer comes from ws_payload_alloc / ws_payload_free (src/link.cpp)
#    instead of malloc / free: a frame goes into a buffer reserved at start. On bad Wi-Fi the
#    TCP stack holds out-of-order segments and the heap has no 48 KB block left by then.
from pathlib import Path

Import("env")  # noqa: F821 - provided by PlatformIO

src = Path(env.subst("$PROJECT_LIBDEPS_DIR"), env.subst("$PIOENV"), "WebSockets/src")


def patch(name: str, pairs: list[tuple[str, str]], what: str) -> None:
    path = src / name
    text = path.read_text()
    patched = text
    for old, new in pairs:
        if new not in patched:
            if old not in patched:
                raise SystemExit(f"patch_websockets: {name} changed, cannot apply: {old!r}")
            patched = patched.replace(old, new)
    if patched != text:
        path.write_text(patched)
        print(f"patch_websockets: {what}")


if (src / "WebSockets.h").exists():
    patch("WebSockets.h", [(
        "#define WEBSOCKETS_MAX_DATA_SIZE (15 * 1024)",
        "#define WEBSOCKETS_MAX_DATA_SIZE (64 * 1024)",
    )], "message limit raised to 64 KB")
    patch("WebSockets.cpp", [
        ('#include "WebSockets.h"\n',
         '#include "WebSockets.h"\n\n'
         '// Tablo: message buffers from the application (firmware/src/link.cpp).\n'
         'void * ws_payload_alloc(size_t size);\n'
         'void ws_payload_free(void * p);\n'),
        ("payload = (uint8_t *)malloc(header->payloadLen + 1);",
         "payload = (uint8_t *)ws_payload_alloc(header->payloadLen + 1);"),
        ("        if(payload) {\n            free(payload);\n        }",
         "        if(payload) {\n            ws_payload_free(payload);\n        }"),
        ("        free(payload);\n        clientDisconnect(client, 1002);",
         "        ws_payload_free(payload);\n        clientDisconnect(client, 1002);"),
    ], "message buffers from ws_payload_alloc")
else:
    print("patch_websockets: WebSockets not installed yet, run the build again")
