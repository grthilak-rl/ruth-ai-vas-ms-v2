# Ruth AI Frontend Dockerfile
# React application built with Vite, served via nginx
#
# Build: docker build -t ruth-ai-frontend .
# Run:   docker run -p 3300:80 -e VAS_PROXY_URL=http://10.30.250.99:8085 ruth-ai-frontend
#
# Environment Variables:
#   VAS_PROXY_URL - VAS backend URL for /v2/ proxy (default: http://localhost:8085)

# ============================================
# Build stage - compile TypeScript and build
# ============================================
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the application
# Note: Environment variables are baked in at build time
ENV VITE_API_BASE_URL=""
RUN npm run build

# ============================================
# Production stage - nginx static server
# ============================================
FROM nginx:alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy nginx config template (will be processed at startup)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy built static files from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Set default VAS URL (can be overridden at runtime)
ENV VAS_PROXY_URL=http://localhost:8085

# Create non-root user and set permissions
RUN adduser -D -u 1000 appuser && \
    chown -R appuser:appuser /usr/share/nginx/html && \
    chown -R appuser:appuser /var/cache/nginx && \
    chown -R appuser:appuser /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R appuser:appuser /var/run/nginx.pid && \
    chown -R appuser:appuser /etc/nginx/templates && \
    chown -R appuser:appuser /etc/nginx/conf.d

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:80/ || exit 1

# nginx:alpine automatically processes /etc/nginx/templates/*.template files
# using envsubst and outputs to /etc/nginx/conf.d/
# Start nginx (the default entrypoint handles template substitution)
CMD ["nginx", "-g", "daemon off;"]
