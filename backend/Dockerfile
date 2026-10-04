FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run as an unprivileged user
RUN groupadd --system app && useradd --system --gid app app \
    && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Liveness check against the health endpoint (no extra packages needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4)"

# Run the application (no --reload in the image; dev mode is a compose override)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
