FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends chromium fonts-liberation \
  && rm -rf /var/lib/apt/lists/*

RUN useradd --system --create-home --user-group --groups audio,video --shell /usr/sbin/nologin chall

ENV NODE_ENV=production \
    PORT=3000 \
    APP_URL=http://localhost:3000 \
    PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app/src
COPY src/package*.json ./
RUN npm ci --omit=dev
COPY src ./
COPY public /app/public

WORKDIR /app/bot
COPY bot/package*.json ./
RUN npm ci --omit=dev
COPY bot ./

WORKDIR /app
USER chall

EXPOSE 3000
CMD ["node", "/app/src/server.js"]
