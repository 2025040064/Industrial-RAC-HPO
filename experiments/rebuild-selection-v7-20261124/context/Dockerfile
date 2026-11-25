FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.lock ./
RUN python3 -m venv /opt/harness \
    && /opt/harness/bin/pip install --only-binary=:all: -r requirements.lock setuptools==80.9.0 wheel==0.45.1
COPY sdk/ ./sdk/
RUN /opt/harness/bin/pip install --no-deps --no-build-isolation ./sdk \
    && /opt/harness/bin/pip check \
    && /opt/harness/bin/pip list --format=freeze > /opt/harness/installed.txt

FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
ENV PATH=/opt/harness/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BASELINE_CPU_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
WORKDIR /app
COPY --from=build /opt/harness /opt/harness
COPY app/ /app/
COPY source-files.json /app/source-files.json
ENTRYPOINT ["python3", "/app/harness.py"]
