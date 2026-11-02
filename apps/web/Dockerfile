# syntax=docker/dockerfile:1
# Shilpa studio (Next.js 16, standalone output). Build context: apps/web
#   docker build -t shilpa-web apps/web
# The API origin is a RUNTIME setting (SHILPA_API_ORIGIN, see docker-entrypoint.sh).

ARG NODE_VERSION=24.22.2

FROM node:${NODE_VERSION}-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Placeholder baked into the rewrite destination; replaced at container start. Must stay a valid URL.
ARG SHILPA_API_ORIGIN=http://shilpa-api-origin.placeholder.invalid:8000
ENV SHILPA_API_ORIGIN=${SHILPA_API_ORIGIN}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    SHILPA_API_ORIGIN=http://api:8000
# Non-root. Directories are owned by it so the entrypoint can rewrite the origin in place (sed -i needs dir write).
RUN groupadd --system --gid 10001 shilpa && useradd --system --uid 10001 --gid shilpa --no-create-home shilpa
COPY --from=build --chown=shilpa:shilpa /app/.next/standalone ./
COPY --from=build --chown=shilpa:shilpa /app/.next/static ./.next/static
COPY --from=build --chown=shilpa:shilpa /app/public ./public
COPY --chown=shilpa:shilpa docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0555 /usr/local/bin/docker-entrypoint.sh && find /app -type d -exec chown shilpa:shilpa {} +
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/login').then(r=>process.exit(r.status===200?0:1)).catch(()=>process.exit(1))"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node", "server.js"]
