# Dockerfile for the "авто скрин для perplexity" service
# Node.js + Playwright service that captures screenshots and calls the Perplexity API.

# Use the official Playwright image: browsers and OS dependencies are preinstalled.
FROM mcr.microsoft.com/playwright:v1.44.0-jammy

# Create app directory
WORKDIR /app

# Set production environment
ENV NODE_ENV=production

# Install dependencies first (better layer caching)
COPY package*.json ./
RUN npm ci --omit=dev || npm install --omit=dev

# Copy the rest of the application source
COPY . .

# Persisted runtime directories from .env.example
# PLAYWRIGHT_PROFILE_DIR=./pw-profile, ARTIFACT_DIR=./artifacts
RUN mkdir -p ./pw-profile ./artifacts
VOLUME ["/app/pw-profile", "/app/artifacts"]

# The service listens on PORT (default 8787 in .env.example)
ENV PORT=8787
EXPOSE 8787

# Start the application
CMD ["npm", "start"]
