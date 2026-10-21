# Tablo — софт: сбои, развёртывание, секреты (§11–13)

> Часть проекта софта, индекс — [`tablo-software.md`](../../tablo-software.md). Номера §N сквозные по всем частям.

## 11. Сбои

| Что упало | Экран | Кнопки |
|---|---|---|
| **Wi-Fi** | Кадр остаётся, часы идут по внутренним часам; через `offline_after_s` — плашка «offline since» | Инверсия и откат через 1,5 с |
| **Сервис** | То же, облако в статусе гаснет | То же |
| **HA** (сервис жив) | Домик в статусе гаснет, блок Home и плитки — последние известные | `button_result ok:false`, плитка откатывается |
| **infomaster** (не отвечает, 401, неверный ответ) | Дедлайны, новости и оценки — последние сохранённые; через 10 мин — значок `mdi:database-off` в строке статуса (`health.data: false`) | — |
| **Источник внутри infomaster** | Надпись в своём блоке по `/api/status` (§7.1–7.5): *HSE login needed*, *the university app unavailable* (3 ч), *N sheet(s) failing* / *sheets unavailable*, *news unavailable* (3 ч). Ошибки РУЗ, почты и Telegram — в теме «Система» infomaster | — |
| **Лента пар** | Сохранённая; через 12 ч — *timetable unavailable* | — |
| **Погода** | Прогноз сдвигается по часам; через 3 ч — *no weather* | — |
| **Перезапуск сервиса** | Плата переподключается, получает конфиг и кадр | — |

---

## 12. Развёртывание и ресурсы

**Разработка** — на Маке, сервис ходит в настоящий HA на `192.168.1.50:8123`.

**Боевой запуск** — Docker Compose на `server` ([`service/compose.yaml`](../../service/compose.yaml)), развёрнут 18.10:
- Каталог `~/tablo` на хосте: код из `service/`, `.env` и `data/` (SQLite с последними ответами infomaster и конфиг от HA). Обновить код — rsync `service/` и `docker compose up -d --build`. Если хост не достаёт до Docker Hub или PyPI, образ собирается на Маке (`docker buildx build --platform linux/amd64 -t tablo:latest --load .`) и переносится через `docker save | ssh server docker load`.
- Сеть bridge, порт открыт только на LAN-адресе хоста, DNS задан явно (`dns:`). Не `network_mode: host`: при нём контейнер берёт DNS хоста, а HA однажды уже ломался из-за этого.
- HA доступен по `192.168.1.50:8123` (`TABLO_HA_URL` в compose).
- **infomaster:** Tablo подключён к его docker-сети `infomaster` как к внешней (`networks: [default, infomaster]`) и ходит на `http://infomaster:8081` по имени сервиса. Сеть создаёт compose infomaster, поэтому он запускается раньше Tablo. Порт infomaster на хост не публикуется.
- **Переход на infomaster** (21.10, одним шагом, порядок — в `tablo-migration.md` infomaster, раздел 2): `docker compose down` Tablo → `import-tablo` в infomaster из копии `tablo.db` → infomaster со всеми источниками → `.env` и конфиг Tablo по §13 и §6.5, `docker compose up -d --build` → обновить и перезагрузить интеграцию HA, удалить осиротевшие сущности (списки дел, датчики LLM). В `data/config.yaml` на хосте не должно остаться секций `grades`, `hseapp`, `news`, `mail`, `subjects`: сервис их не принимает (HA при следующей отправке пришлёт уже чистый конфиг).
- Том `./data` для SQLite и сохранённого конфига. `mem_limit: 256m`, `TZ=Europe/Moscow`.

**Память** (замер 18.10 в контейнере):

| Состояние | RSS |
|---|---|
| После старта, все источники и разбор таблиц | 124 МБ, пик 126 МБ |
| `docker stats` | 95 МБ из 256 МБ |

Замер до перехода на infomaster; без Haiku, таблиц, почты и Telegram память меньше — перемерить после деплоя. CPU в ожидании около нуля.

---

## 13. Секреты и приватность

| Секрет | Где хранится |
|---|---|
| Токен HA, токен infomaster (`TABLO_UNIMASTER_TOKEN` = `API_TOKEN` infomaster), токены платы и API | `.env` сервиса |
| Ссылка на ленту пар (с `CALENDAR_SECRET` infomaster), пароли Wi-Fi для QR | Настройки интеграции в HA (`.storage`) |

- Каждый секрет — в одном месте. Ключ Anthropic, почта (`TABLO_MAIL_USER`, `TABLO_MAIL_PASSWORD`), ссылка РУЗ (`TABLO_ICAL_URL`) и токен the university app теперь только у infomaster; из `.env` Tablo их убрать. Ключ `hseapp.auth` из `tablo.db` сервис удаляет сам при старте.
- В репозиторий секреты не попадают: в нём только `.env.example`.
- Сервис слушает только локальную сеть, наружу не публикуется.
- Таблицы оценок, письма и чаты Tablo больше не читает: правила приватности для них — у infomaster.
