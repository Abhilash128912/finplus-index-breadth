FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Symlink src as finplus_index_breadth for seamless package resolution
RUN ln -sf /app/src /app/finplus_index_breadth

# Set python path
ENV PYTHONPATH=/app:/app/src:/app/finplus_index_breadth
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
