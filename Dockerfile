# Use the official slim Python runtime
FROM python:3.12-slim

# Metadata
LABEL maintainer="krishnabandewar"
LABEL description="OpenAI Status Page tracker — async incident monitor"

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY tracker.py .

# Run the tracker
CMD ["python", "tracker.py"]
