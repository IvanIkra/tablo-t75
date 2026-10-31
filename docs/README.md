# Tablo — software design (index)

The contract for the service, the emulator, the Home Assistant integration and the
Tablo T75 firmware. The product and the hardware are described in
[`hardware.md`](hardware.md); where the two disagree, the software documents win.

The design is split into parts so you only read what you need. Section numbers §N run
through all the parts; a reference like "§3.3" points into the matching part.

Status on 31.10.2026: stages 1–8 and 10 are done (deadlines, news, grades and classes
come from infomaster, §7); the firmware is nearly done (§10): a live panel in its
enclosure. The hardware is built.

| Part | Sections |
|---|---|
| [`01-architecture.md`](software/01-architecture.md) | §1 the system, §2 who draws what (screen zones) |
| [`02-protocol.md`](software/02-protocol.md) | §3 board ↔ service protocol, §4 buttons, §5 full-screen screens |
| [`03-service.md`](software/03-service.md) | §6 the service: stack, structure, layout, HTTP API, config |
| [`04-sources.md`](software/04-sources.md) | §7 sources: infomaster (deadlines, news, grades), classes, weather, home, fitting text |
| [`05-ha-integration.md`](software/05-ha-integration.md) | §8 Home Assistant integration |
| [`06-emulator-firmware.md`](software/06-emulator-firmware.md) | §9 emulator, §10 firmware |
| [`07-failures-deploy.md`](software/07-failures-deploy.md) | §11 failures, §12 deployment, §13 secrets |
| [`08-plan.md`](software/08-plan.md) | §14 repository layout, §15 work plan, §16 open questions |
