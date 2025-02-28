# Use slim version of Python 3.12 as the base image
FROM python:3.12-slim
ARG DEBIAN_FRONTEND=noninteractive

# Install system dependencies required by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /usr/src/app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies without caching
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir litellm asyncpraw

# Copy all local files into the container
COPY . .

# Command to run when the container starts
CMD ["python", "main.py"]