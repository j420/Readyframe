# Build and deploy by immutable digest. This image contains no SCM token, shell
# entrypoint, host mount, Docker socket, package manager, or Pilot tool adapter.
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
WORKDIR /app
COPY deploygrade /app/deploygrade
RUN groupadd --gid 10001 deploygrade && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin deploygrade \
    && chown -R 10001:10001 /app
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
ENTRYPOINT ["python", "-m", "deploygrade.worker.service"]
