FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first, so code changes don't reinstall them. tzdata: zoneinfo needs it, slim has none.
COPY pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt tzdata \
    && rm /tmp/req.txt

# Run from the source tree: app.py finds assets/ and emulator/ next to tablo/.
COPY config.yaml .
COPY assets assets
COPY emulator emulator
COPY tablo tablo

EXPOSE 8765
CMD ["python", "-m", "tablo", "--config", "config.yaml", "--data", "data"]
