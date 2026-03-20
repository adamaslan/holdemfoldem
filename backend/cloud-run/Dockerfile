# Stage 1: Build - install dependencies with micromamba
FROM mambaorg/micromamba:1.5.6 as builder

COPY --chown=$MAMBA_USER:$MAMBA_USER cloud-run/environment.yml /tmp/environment.yml

RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean --all --yes

# Stage 2: Runtime
FROM mambaorg/micromamba:1.5.6

COPY --from=builder /opt/conda /opt/conda

WORKDIR /app

# FastAPI entry point (cloud-run specific)
COPY --chown=$MAMBA_USER:$MAMBA_USER cloud-run/main.py ./main.py

# MCP source (canonical package used by main.py)
COPY --chown=$MAMBA_USER:$MAMBA_USER src ./src

# fibonacci sub-package lives at project root in the existing repo
COPY --chown=$MAMBA_USER:$MAMBA_USER fibonacci ./fibonacci

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "main.py"]
