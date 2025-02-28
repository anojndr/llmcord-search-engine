# Use slim version of Python 3.12 as the base image
FROM python:3.12-slim

ARG DEBIAN_FRONTEND=noninteractive

# Set the working directory inside the container
WORKDIR /usr/src/app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies without caching
RUN pip install --no-cache-dir -r requirements.txt

# Copy all local files into the container
COPY . .

# Command to run when the container starts
CMD ["python", "main.py"]