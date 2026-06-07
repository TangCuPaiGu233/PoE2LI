FROM python:3.10-slim

WORKDIR /app

# Install dependencies with Chinese mirror
COPY backend/requirements.txt .
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt

# Copy backend application
COPY backend/ .

# Copy pob_decoder from project root
COPY pob_decoder.py /app/pob_decoder.py

# Create data directory for SQLite
RUN mkdir -p /app/data

# Copy entrypoint script for running migrations before startup
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose port
EXPOSE 8000

# Entrypoint runs alembic migrations, then exec's the CMD
ENTRYPOINT ["/app/entrypoint.sh"]

# Run
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
