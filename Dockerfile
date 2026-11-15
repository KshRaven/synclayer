FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/KshRaven/synclayer"
LABEL org.opencontainers.image.description="SyncLayer server"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SL_HOST=0.0.0.0 \
    SL_PORT=8787 \
    SL_CONFIG_DIR=/data/config \
    SL_STORAGE_ROOT=/data/files

WORKDIR /app
COPY pyproject.toml README.md ./
COPY synclayer ./synclayer
RUN pip install . && useradd --system --uid 10001 --home-dir /data synclayer \
    && mkdir -p /data/config /data/files && chown -R synclayer:synclayer /data

USER synclayer
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('SL_PORT','8787'), timeout=4)" || exit 1

CMD ["synclayer", "server", "serve"]
