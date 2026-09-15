# ==============================================================================
# CivicTrace Bhopal - Production Container Image
# ==============================================================================
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
# Hugging Face Spaces expects port 7860 by default; Render/Cloud Run pass $PORT dynamically
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

# Install curl for container health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, datasets, and entrypoint
COPY app/ ./app/
COPY data/ ./data/
COPY start.sh .

# Ensure executable permissions and set up non-root application user (UID 1000 required by HF Spaces)
RUN chmod +x start.sh \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

# Health check against operator queue endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/tickets || exit 1

# Launch via auto-seeding production entrypoint
CMD ["./start.sh"]
