FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir 'fastapi>=0.110,<1' 'uvicorn>=0.27,<1' 'redis>=5,<7'
COPY integration/mock_runtime /app/mock_runtime
EXPOSE 8000
CMD ["uvicorn", "mock_runtime.app:app", "--host", "0.0.0.0", "--port", "8000"]
