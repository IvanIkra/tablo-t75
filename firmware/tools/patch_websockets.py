# PlatformIO pre-script: lift arduinoWebSockets' 15 KB message limit.
# The library defines WEBSOCKETS_MAX_DATA_SIZE without #ifndef, so -D cannot override it,
# and a frame is one 48 020-byte message (§3.2).
from pathlib import Path

Import("env")  # noqa: F821 - provided by PlatformIO

header = Path(env.subst("$PROJECT_LIBDEPS_DIR"), env.subst("$PIOENV"), "WebSockets/src/WebSockets.h")
if header.exists():
    text = header.read_text()
    patched = text.replace("#define WEBSOCKETS_MAX_DATA_SIZE (15 * 1024)", "#define WEBSOCKETS_MAX_DATA_SIZE (64 * 1024)")
    if patched != text:
        header.write_text(patched)
        print("patch_websockets: message limit raised to 64 KB")
else:
    print("patch_websockets: WebSockets not installed yet, run the build again")
