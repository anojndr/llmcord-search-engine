# Use slim version of Python 3.12 as the base image
FROM python:3.12-slim
ARG DEBIAN_FRONTEND=noninteractive

# Set the working directory inside the container
WORKDIR /usr/src/app

# Copy all local files into the container
COPY . .
# Ensure system_prompt.txt is included in the container
COPY system_prompt.txt .

# Install Python dependencies without caching
RUN pip install --no-cache-dir -r requirements.txt

# Command to run when the container starts
CMD ["python", "llmcord.py"]