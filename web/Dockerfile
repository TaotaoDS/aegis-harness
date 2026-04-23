# =============================================================================
# AegisHarness — Frontend Dockerfile
# =============================================================================
# Multi-stage build:
#   Stage 1 (deps)     — install node_modules (cached layer)
#   Stage 2 (builder)  — next build (produces .next/standalone)
#   Stage 3 (runtime)  — minimal Node image with only the standalone output
#
# next.config.mjs must have: output: "standalone"
#
# Build:   docker build -t harness-frontend ./web
# Run:     docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://backend:8000 harness-frontend
# =============================================================================

# ---------- Stage 1: install dependencies ----------
FROM node:20-alpine AS deps

WORKDIR /app

# Copy manifests first for layer-cache efficiency
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline


# ---------- Stage 2: build ----------
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Bake in the backend URL at build time (can be overridden at runtime via env)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build


# ---------- Stage 3: minimal runtime ----------
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production
# Disable Next.js telemetry in production containers
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN addgroup -g 1001 -S nodejs \
 && adduser  -S nextjs -u 1001

# Copy only what the standalone server needs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static    ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public          ./public

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
