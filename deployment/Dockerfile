# Dockerfile for Thakii Lecture2PDF Backend Service
FROM python:3.10-slim

# Install system dependencies required for video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    build-essential \
    lsof \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install service requirements first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create lecture2pdf directory and copy from local
RUN mkdir -p /lecture2pdf
COPY lecture2pdf-external/ /lecture2pdf/

# Install lecture2pdf dependencies
COPY lecture2pdf-external/requirements.txt /tmp/lecture2pdf-requirements.txt
RUN pip install --no-cache-dir -r /tmp/lecture2pdf-requirements.txt
RUN pip install --no-cache-dir moviepy

# Copy the entire backend directory structure
COPY . /app/

# Copy Firebase configuration files
COPY firebase/ /app/firebase/

# Create necessary directories
RUN mkdir -p videos generated_pdfs logs instance

# Set environment variables
ENV LECTURE2PDF_PATH=/lecture2pdf
ENV PYTHONPATH=/app:/lecture2pdf
ENV FLASK_APP=api/app.py
ENV FLASK_ENV=production
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/firebase-service-account.json

# Expose port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Default command (can be overridden)
CMD ["python", "api/app.py"] 