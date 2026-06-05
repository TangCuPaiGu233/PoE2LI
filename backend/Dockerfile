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

# Expose port
EXPOSE 8000

# Run
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
