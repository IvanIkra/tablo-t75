# Tablo service

> infomaster переименован в infomaster; новые имена (токен, секция конфига, адрес, сеть) — в [`../tablo-software.md`](../tablo-software.md), в начале.

Сервис Tablo T75: берёт данные у infomaster и Open-Meteo, рисует кадр 800×480 в 1 бит, держит WebSocket с платой. Проект и протокол — в [`../tablo-software.md`](../tablo-software.md).

Демо-данные блоков (`tablo/stub.py`) включаются переключателями в эмуляторе; без них блоки показывают только настоящие данные.

## Запуск

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

```bash
.venv/bin/python -m tablo --config config.yaml
```

Эмулятор: <http://localhost:8765/emu>. Кнопки — мышью или клавишами 1–8, удержание ≥ 600 мс — долгое нажатие. Токен платы можно передать в адресе: `/emu?token=…`.

Тесты:

```bash
.venv/bin/python -m pytest -q
```

## Источники

Личные настройки — в `config.local.yaml` (не в git, накладывается поверх `config.yaml`), секреты — в `.env`. Состояние — в `data/tablo.db`.

- **Дедлайны, новости, оценки** — из infomaster (§7.1): `infomaster.url` (по умолчанию `http://infomaster:8081`, docker-сеть `infomaster`), токен — `API_TOKEN` infomaster в `.env` как `TABLO_UNIMASTER_TOKEN`. Настройки этих блоков (the university app, таблицы, чаты, почта, словарь, свои дедлайны) — в Mini App infomaster.
- **Пары** — лента infomaster `http://infomaster:8081/calendar/<CALENDAR_SECRET>/tablo.ics`: `ical.url` в `config.local.yaml` или в форме «Источники» HA.
- **Погода**: Open-Meteo без ключа, секция `weather`.
- **Дом**: долгоживущий токен HA (Профиль → Безопасность → «Долгоживущие токены доступа») в `.env` как `TABLO_HA_TOKEN`, адрес — `ha.url`. Блок Home — строки-шаблоны HA в секции `home.rows` (§8.3), правятся в форме интеграции; имена сущностей Moonraker сверить после установки интеграции. В эмуляторе снять флажок *fake HA*, чтобы видеть настоящий дом. Скрипты для долгих нажатий — [`../ha-integration/scripts/tablo.yaml`](../ha-integration/scripts/tablo.yaml), вставить в `scripts.yaml` HA.

На Маке infomaster по имени `infomaster` не виден: для эмулятора с живыми данными `infomaster.url` и `ical.url` в `config.local.yaml` указывают на адрес, где его API доступен (например, через `ssh -L`).

## Что где

| Файл | Что |
|---|---|
| `tablo/protocol.py` | Формат кадра (§3.2) и зоны прошивки |
| `tablo/config.py` | Схема конфига: `config.yaml` или `PUT /api/config` от интеграции HA; `to_dict` для `GET /api/config` |
| `tablo/hub.py` | WebSocket с платой, кадры, действия кнопок, полноэкранные экраны |
| `tablo/app.py` | HTTP API (§6.4), раздача эмулятора |
| `tablo/model.py`, `tablo/builder.py` | Модель экрана и её сборка из источников |
| `tablo/render/` | Вёрстка (Pillow), пиксельные значки (`pixels.py`) и шрифты (`pixelfont.py`), QR и сообщения, упаковка в 1 бит |
| `tablo/ha.py` | Клиент HA по WebSocket (состояния, `call_service`, `tablo_button`) и фейковый HA в памяти: 5 светильников, VPN-точка, датчик, принтер; Tuya отвечает с задержкой 2 с |
| `tablo/sources/` | Источники: `infomaster.py` (дедлайны, новости, оценки и статус из infomaster), `ical.py` (пары из `tablo.ics`), `weather.py` (Open-Meteo) |
| `tablo/store.py` | SQLite: последние удачные ответы источников |
| `tablo/stub.py` | Демо-данные блоков |
| `emulator/` | Эмулятор платы: та же логика, что будет в прошивке |
| `assets/` | Шрифты Inter (OFL) и Material Design Icons (Pictogrammers Free License); `fonts/pixel/` — пиксельные версии Inter для экрана, правятся руками |
| `tools/pixel_fonts.py` | Делает пиксельные шрифты из Inter (только недостающие, правки не затирает) и листы для просмотра |

## HTTP API

Изменяющие запросы — с заголовком `Authorization: Bearer <api_token>` (по умолчанию `dev-api-token`).

```bash
curl -X POST localhost:8765/api/overlay/message -H 'Authorization: Bearer dev-api-token' -d '{"title":"Hi","text":"Hello from curl","duration_s":10}'
```

`GET /frame.png` — текущий кадр, `GET /api/status` — состояние платы и кадра. Остальное — для интеграции HA, список в §6.4.

## Режим шрифта

`display.font_mode` в конфиге: `aliased` (монохромный растеризатор FreeType) или `threshold` (сглаживание и порог 50%). Выберем на живой панели.
