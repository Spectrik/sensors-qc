FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY sensor_qc ./sensor_qc

USER 10001:10001

ENTRYPOINT ["python", "-m", "sensor_qc"]
