# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required by the bot
# - ffmpeg: for all media processing
# - git: can be required for some pip package installations
# - build-essential: required to compile C extensions like TgCrypto for speed
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy the dependency file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY . .

# Tell Docker to run the bot when the container starts
CMD ["python", "bot.py"]