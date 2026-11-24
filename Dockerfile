FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOUSING_DATA_DIR=/data
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --create-home --uid 10001 housing \
    && mkdir -p /data && chown -R housing:housing /app /data
USER housing
EXPOSE 8080
CMD ["python", "-m", "utah_housing", "serve", "--host", "0.0.0.0", "--port", "8080"]
