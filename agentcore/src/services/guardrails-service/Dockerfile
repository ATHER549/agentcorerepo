FROM python:3.12-slim

WORKDIR /app

# Install dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Pre-download NeMo's internal intent-classification embedding model (all-MiniLM-L6-v2-onnx, ~91 MB).
# NeMo Guardrails uses this ONNX model locally for Colang flow intent matching — it does NOT make
# external API calls at runtime. Without pre-downloading here it would be fetched on the first
# guardrail execution, causing a slow cold-start and a network dependency at runtime.
# HF_HOME is set so the cache lands in a predictable layer and persists in the container image.
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "\
from fastembed import TextEmbedding; \
model = TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2'); \
print('NeMo embedding model pre-downloaded OK')"

# Copy application code
COPY app/ app/

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8005/health').raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
