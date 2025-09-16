# Use a lightweight Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements and install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy the Python script
COPY dmarc_monitor.py .

# Expose port 8000 for Prometheus metrics
EXPOSE 8000

# Run the script permanently
CMD ["python", "dmarc_monitor.py"]
