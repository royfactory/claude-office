FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul OFFICE_DATA=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY static ./static
RUN useradd -u 501 -m office && mkdir -p /data && chown office /data
USER office
EXPOSE 3006
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3006/health', timeout=2)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3006", "--log-level", "warning", "--no-access-log"]
