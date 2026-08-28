FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/codeteam-sandbox-requirements.txt
RUN python -m pip install \
    --no-cache-dir \
    --requirement /tmp/codeteam-sandbox-requirements.txt \
    && rm /tmp/codeteam-sandbox-requirements.txt

WORKDIR /workspace
