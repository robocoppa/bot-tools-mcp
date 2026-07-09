FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching. Install the project (which pulls
# fastmcp/aiosmtplib/icalendar/caldav/httpx/openpyxl/python-docx from
# pyproject) without dev extras.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=9110

EXPOSE 9110

# Liveness: hit the app's own UNAUTHENTICATED /health route. NOT /mcp — a bare
# GET on /mcp is rejected by transport+auth rules and reads as unhealthy
# forever. No curl in the slim image, so use python's urllib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9110/health').status==200 else 1)"

CMD ["bot-tools-mcp"]
