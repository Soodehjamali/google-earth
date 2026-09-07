FROM node:20-alpine

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm

# Install dependencies
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install

# Copy application code
COPY . .

# Expose port
EXPOSE 5173

# Run the development server
CMD ["pnpm", "dev", "--host"]
