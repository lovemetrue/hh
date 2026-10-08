FROM python:3.12-slim-bookworm

# The bot drives a real (headed) Chromium under a virtual display: pages behave like on the host.
ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Moscow \
    DATA_DIR=/data \
    HH_USE_SESSION=1 \
    DASH_HOST=0.0.0.0

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.63.0 certifi \
 && playwright install --with-deps chromium \
 && apt-get update && apt-get install -y --no-install-recommends xvfb tzdata \
 && rm -rf /var/lib/apt/lists/*

# xvfb-run needs xauth (separate layer: keeps the heavy Chromium layer cached)
RUN apt-get update && apt-get install -y --no-install-recommends xauth x11vnc novnc websockify \
 && rm -rf /var/lib/apt/lists/*

COPY bot.py letter.py store.py dashboard.py dashboard.html resume_facts.md entrypoint.sh ./

EXPOSE 8765 6080
CMD ["sh", "entrypoint.sh"]
