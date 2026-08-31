# syntax=docker/dockerfile:1.6
# [ChatKit] Next.js frontend — multi-stage standalone build for Scaleway.
# NEXT_PUBLIC_* are baked into the client bundle AT BUILD TIME: the backend URL
# and the ChatKit domainKey must be passed as --build-arg.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ARG NEXT_PUBLIC_CHATKIT_API_URL
ARG NEXT_PUBLIC_CHATKIT_DOMAIN_KEY
ENV NEXT_PUBLIC_CHATKIT_API_URL=${NEXT_PUBLIC_CHATKIT_API_URL}
ENV NEXT_PUBLIC_CHATKIT_DOMAIN_KEY=${NEXT_PUBLIC_CHATKIT_DOMAIN_KEY}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=8080
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 8080
CMD ["node", "server.js"]
