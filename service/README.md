# Tablo service

Сервис Tablo T75: собирает данные, рисует кадр 800×480 в 1 бит, держит WebSocket с платой. Проект и протокол — в [`../tablo-software.md`](../tablo-software.md).

**Этап 1 (готов):** протокол и формат кадра, рендер на демо-данных, кнопки из `config.yaml` через фейковый Home Assistant в памяти, Wi-Fi QR и сообщения, эмулятор платы в браузере. Настоящих источников данных пока нет: погода, дедлайны, оценки, новости и пары — заглушки из `tablo/stub.py`.

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

## Что где

| Файл | Что |
|---|---|
| `tablo/protocol.py` | Формат кадра (§3.2) и зоны прошивки |
| `tablo/config.py` | Схема конфига: `config.yaml` сейчас, `PUT /api/config` от интеграции HA потом |
| `tablo/hub.py` | WebSocket с платой, кадры, действия кнопок, полноэкранные экраны |
| `tablo/app.py` | HTTP API (§6.4), раздача эмулятора |
| `tablo/model.py`, `tablo/builder.py` | Модель экрана и её сборка из источников |
| `tablo/render/` | Вёрстка (Pillow), значки погоды, QR и сообщения, упаковка в 1 бит |
| `tablo/ha.py` | Фейковый HA: 5 светильников, VPN-точка, датчик; Tuya отвечает с задержкой 2 с |
| `tablo/stub.py` | Демо-данные блоков |
| `emulator/` | Эмулятор платы: та же логика, что будет в прошивке |
| `assets/` | Шрифты Inter (OFL) и Material Design Icons (Pictogrammers Free License) |

## HTTP API

Изменяющие запросы — с заголовком `Authorization: Bearer <api_token>` (по умолчанию `dev-api-token`).

```bash
curl -X POST localhost:8765/api/overlay/message -H 'Authorization: Bearer dev-api-token' -d '{"title":"Hi","text":"Hello from curl","duration_s":10}'
```

`GET /frame.png` — текущий кадр, `GET /api/status` — состояние платы и кадра.

## Режим шрифта

`display.font_mode` в конфиге: `aliased` (монохромный растеризатор FreeType) или `threshold` (сглаживание и порог 50%). Выберем на живой панели.
