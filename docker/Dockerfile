FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_ARENA_MAX=2 \
    TZ_OFFSET=8 \
    DATA_DIR=/app/data \
    HTTP_PORT=8080

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/data \
    && chown -R 1000:1000 /app/data

COPY app /app/app
COPY config.example.json /app/config.json

USER 1000:1000
EXPOSE 8080
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3)" || exit 1

# SSE 长连接会常驻占用一个 worker 线程，线程数设为 12，留足并发余量给常规
# API；EventBus 另有限制订阅数，双保险。
#
# waitress 默认会剥离所有 X-Forwarded-* 头，反代部署时应用拿不到真实客户端
# IP，导致限流按反代 IP 单一计数、会话 IP 绑定与审计 IP 全部失真。这里让
# waitress 保留原始头，由应用层 client_ip() 依据 TRUSTED_PROXIES（支持多个
# CIDR）判断是否采信；未配置 TRUSTED_PROXIES 时应用一律忽略 XFF，直连伪造头
# 也不会被信任。waitress 未配置 trusted_proxy 时不会改写 REMOTE_ADDR，因此
# 可信链判断始终基于真实 socket 对端地址。
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--threads=12", "--no-clear-untrusted-proxy-headers", "app.main:app"]
