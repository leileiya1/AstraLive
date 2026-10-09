FROM oven/bun:1 AS build
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
COPY contracts/control-api.openapi.yaml /contracts/control-api.openapi.yaml
ARG VITE_WEBRTC_STUN_URLS=
ARG VITE_WEBRTC_TURN_URLS=
ARG VITE_WEBRTC_TURN_USERNAME=
ARG VITE_WEBRTC_TURN_CREDENTIAL=
RUN bun run build
FROM nginx:1.27-alpine
COPY infra/frontend.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
