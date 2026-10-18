# Tablo — проект софта (индекс)

Контракт для сервиса, эмулятора, интеграции Home Assistant и прошивки Tablo T75. Описание продукта и железа — в [`tablo-project.md`](tablo-project.md). Если описания расходятся, верен софтовый документ.

Документ разбит на части, чтобы читать только нужное. Номера §N сквозные, ссылки вида «§3.3» ведут в соответствующую часть. Полная исходная версия — в [`docs/archive/tablo-software.md`](docs/archive/tablo-software.md).

Статус на 18.10.2026: этапы 1–3 готовы (каркас и эмулятор, оценки, дедлайны), дальше пары. Железо заказано.

| Часть | Разделы |
|---|---|
| [`01-architecture.md`](docs/software/01-architecture.md) | §1 состав системы, §2 кто что рисует (зоны экрана) |
| [`02-protocol.md`](docs/software/02-protocol.md) | §3 протокол плата ↔ сервис, §4 кнопки, §5 полноэкранные экраны |
| [`03-service.md`](docs/software/03-service.md) | §6 сервис: стек, устройство, вёрстка, HTTP API, конфиг |
| [`04-sources.md`](docs/software/04-sources.md) | §7 источники: оценки, дедлайны, пары, погода, новости, дом, вписывание текста |
| [`05-ha-integration.md`](docs/software/05-ha-integration.md) | §8 интеграция Home Assistant |
| [`06-emulator-firmware.md`](docs/software/06-emulator-firmware.md) | §9 эмулятор, §10 прошивка |
| [`07-failures-deploy.md`](docs/software/07-failures-deploy.md) | §11 сбои, §12 развёртывание, §13 секреты |
| [`08-plan.md`](docs/software/08-plan.md) | §14 структура репозитория, §15 план работ, §16 открытые вопросы |
