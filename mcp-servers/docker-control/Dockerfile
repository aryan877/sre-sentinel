FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production && npm cache clean --force

# Copy source code
COPY . .

# Create non-root user for security
# NOTE: On macOS, Docker socket requires root access inside containers
# For production, use proper Docker group permissions on Linux
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001 && \
    chown -R nodejs:nodejs /app

# USER nodejs  # Commented out for macOS Docker socket access

# Start the server
CMD ["node", "index.js"]