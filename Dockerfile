# ---- Base Python image ----
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies (if requirements.txt exists)
COPY requirements.txt* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy project files
COPY execution/ ./execution/
COPY directives/ ./directives/
COPY .env* ./

# Default: drop into a shell so you can run scripts manually
CMD ["bash"]
