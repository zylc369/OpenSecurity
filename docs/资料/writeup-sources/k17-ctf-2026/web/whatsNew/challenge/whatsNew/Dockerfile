FROM node:20-bookworm-slim

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY . .

ENV NODE_ENV=production
# Unique event-wide port so the bot's origin (56773-<id>.<domain>) can only ever be a
# whatsNew instance. Must match the instantiator `port` and the bot originTemplate.
ENV PORT=56773
EXPOSE 56773
CMD ["npm", "start"]
