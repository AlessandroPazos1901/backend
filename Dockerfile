FROM python:3.11-slim
WORKDIR /app
COPY MonitorAedes-Backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY MonitorAedes-Backend /app
EXPOSE 8000
CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]
