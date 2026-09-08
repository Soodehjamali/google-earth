FROM node:20-alpine

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm

# Copy package definitions
COPY package.json pnpm-lock.yaml* ./

# Install dependencies allowing build scripts (like esbuild) for Docker
RUN pnpm install --dangerously-allow-all-builds

# Copy application code
COPY . .

EXPOSE 5173

CMD ["pnpm", "dev", "--host"]