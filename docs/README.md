# Tablo — проект софта (индекс)

Контракт для сервиса, эмулятора, интеграции Home Assistant и прошивки Tablo T75. Описание продукта и железа — в [`tablo-project.md`](tablo-project.md). Если описания расходятся, верен софтовый документ.

Документ разбит на части, чтобы читать только нужное. Номера §N сквозные, ссылки вида «§3.3» ведут в соответствующую часть. Полная исходная версия — в [`docs/archive/tablo-software.md`](docs/archive/tablo-software.md).

Статус на 31.10.2026: этапы 1–8 и 10 готовы (данные дедлайнов, новостей, оценок и пар — от infomaster, §7), прошивка почти готова (§10): живая панель в корпусе, fw-0.5. Железо собрано.

| Часть | Разделы |
|---|---|
| [`01-architecture.md`](software/01-architecture.md) | §1 состав системы, §2 кто что рисует (зоны экрана) |
| [`02-protocol.md`](software/02-protocol.md) | §3 протокол плата ↔ сервис, §4 кнопки, §5 полноэкранные экраны |
| [`03-service.md`](software/03-service.md) | §6 сервис: стек, устройство, вёрстка, HTTP API, конфиг |
| [`04-sources.md`](software/04-sources.md) | §7 источники: infomaster (дедлайны, новости, оценки), пары, погода, дом, вписывание текста |
| [`05-ha-integration.md`](software/05-ha-integration.md) | §8 интеграция Home Assistant |
| [`06-emulator-firmware.md`](software/06-emulator-firmware.md) | §9 эмулятор, §10 прошивка |
| [`07-failures-deploy.md`](software/07-failures-deploy.md) | §11 сбои, §12 развёртывание, §13 секреты |
| [`08-plan.md`](software/08-plan.md) | §14 структура репозитория, §15 план работ, §16 открытые вопросы |
