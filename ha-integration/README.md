# Интеграция Tablo для Home Assistant

Контракт — [§8](../docs/software/05-ha-integration.md). Проверена на HA 2026.4.4.

## Установка

1. Скопировать `custom_components/tablo` в `/config/custom_components/tablo` (на `server` это `<HA config>/custom_components/tablo`).
2. Перезапустить HA.
3. Настройки → Устройства и службы → Добавить интеграцию → **Tablo T75**: адрес сервиса (`http://192.168.1.50:8765`) и токен API: `TABLO_API_TOKEN` из `.env` сервиса, а если он там не задан — `dev-api-token`. Конфиг сервиса импортируется сам.
4. Скрипты для долгих нажатий — из [`scripts/tablo.yaml`](scripts/tablo.yaml).
5. После обновления с версии со списками дел: удалить в HA осиротевшие сущности `todo.tablo_*` и датчики «LLM run: …», «LLM cost today»; в форме «Источники» указать ссылку на `tablo.ics` infomaster и имя его бота.

Сервису нужен свой долгоживущий токен HA (`TABLO_HA_TOKEN`) от пользователя-администратора: без прав администратора HA не даёт ему публиковать события `tablo_button` и `tablo_changed`.

## Что где

| Файл | Что |
|---|---|
| `__init__.py` | Подключение, перевод старых записей (1.1 → 1.2: без настроек источников infomaster), действия `tablo.*`, события `tablo_changed`, уведомление о входе в the university app со ссылкой на бота infomaster |
| `config_flow.py` | Подключение к сервису и формы «Настроить»: кнопки, Wi-Fi, источники, дом, экран |
| `forms.py` | Многострочные поля форм ↔ списки конфига |
| `coordinator.py`, `api.py` | Опрос сервиса и HTTP-клиент |
| `device_trigger.py` | Триггеры «кнопка N, короткое / долгое» |
| `binary_sensor.py`, `sensor.py` | «Подключено», уровень Wi-Fi, последняя связь |

## Тесты

Тесты поднимают настоящий сервис с фейковым домом и гоняют интеграцию в тестовом HA.

```bash
python3.14 -m venv .venv && .venv/bin/pip install homeassistant==2026.4.4 pytest-homeassistant-custom-component -e ../service
```

```bash
.venv/bin/pytest
```
