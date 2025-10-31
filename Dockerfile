# Use slim Python image (saves ~600MB, faster pull)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies in one layer (cached unless Dockerfile changes)
RUN apt-get -qq update && apt-get -qq install -y --no-install-recommends \
    git \
    wget \
    ffmpeg \
    mediainfo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached unless requirements.txt changes)
COPY requirements.txt .

# Install Python packages (cached unless requirements change)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (changes most frequently, so last)
COPY . .

# Explicitly remove any old backup files and caches to ensure clean deployment
RUN rm -f app_old.py db_manager_old.py 2>/dev/null || true && \
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find . -name "*.pyc" -delete 2>/dev/null || true && \
    find . -name "*.pyo" -delete 2>/dev/null || true && \
    echo "=== Files in /app ===" && ls -la /app/*.py | head -20

# Make startup script executable
RUN chmod +x cloud.sh

CMD ["bash", "cloud.sh"]
