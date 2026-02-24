FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       libjpeg-dev \
       zlib1g-dev \
       curl \
       netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Upgrade pip, wheel, and setuptools for security (CVE-2026-1703, CVE-2026-24049)
RUN pip install --no-cache-dir --upgrade 'pip>=26.0' 'wheel>=0.46.2' 'setuptools>=80.10.2'

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn[standard] psycopg2-binary

# Copy application
COPY . .


# Set permissions
RUN mkdir -p staticfiles media \
    && chown -R appuser:appuser /app

# Copy entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "horilla.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
