FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PORT=8080
ENV MAPCP_BIND_HOST=0.0.0.0

WORKDIR /app

COPY requirements-deploy.txt /app/requirements-deploy.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements-deploy.txt && python -m pip check

RUN groupadd --gid 10001 mapcp && useradd --uid 10001 --gid 10001 --create-home mapcp

COPY --chown=10001:10001 *.py /app/
COPY --chown=10001:10001 project_data/ /app/project_data/
COPY --chown=10001:10001 docs/ /app/docs/

RUN mkdir -p /app/outputs && chown 10001:10001 /app /app/outputs

USER 10001:10001

EXPOSE 8080

CMD ["python", "server_http.py"]
