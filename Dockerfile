# Lidl Plus e-nyugta archívum – webes felület + ütemezett frissítés
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Europe/Budapest

# A PDF-renderhez Chromium kell; a Liberation Mono metrikailag a Courier New
# párja, így a papír-hű tördelés nem csúszik el.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fonts-liberation \
      fonts-dejavu-core \
      libatomic1 \
      tzdata \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# A felhasználó és az adatmappák a kód ELŐTT készülnek, így a kódváltozás
# nem invalidálja újra ezt a réteget. A Playwright a böngészőket
# világ-olvasható (644/755) módban telepíti, ezért külön chmod nem kell.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin lidl \
 && mkdir -p /data /nyugtak \
 && chown -R lidl:lidl /data /nyugtak

COPY lidl ./lidl

USER lidl
EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=10s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=8).status == 200 else 1)"

CMD ["python", "-m", "lidl", "serve", "--host", "0.0.0.0", "--port", "8765"]
