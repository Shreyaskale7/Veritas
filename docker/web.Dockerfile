# Veritas web: builds the React app, serves it with Caddy (automatic HTTPS) and proxies /api to the API container.
FROM node:22-alpine AS build
WORKDIR /src
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend ./
ENV VITE_API_BASE=""
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv
COPY docker/Caddyfile /etc/caddy/Caddyfile
