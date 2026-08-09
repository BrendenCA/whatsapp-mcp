# whatsapp-mcp: two services, two runtime stages, one file.
# Select with `target:` in docker-compose.yml.
#
#   target: bridge  -> Go + whatsmeow. Holds the WhatsApp linked-device
#                      connection, archives messages to SQLite, REST on :8080.
#   target: mcp     -> Python + FastMCP. Reads the bridge's SQLite directly and
#                      calls its REST API. Serves the MCP endpoint on :8000.
#
# Build context is the repository root. Each stage COPYs its own
# subdirectory from that context.
#
# Debian rather than Alpine. The bridge needs CGO (mattn/go-sqlite3 compiles
# SQLite itself) and the server pins cryptography<49, which publishes
# manylinux aarch64 wheels but no dependable musl ones: building on glibc
# avoids dragging a Rust toolchain into the image.

# ------------------------------------------------------------ bridge build
FROM golang:1.25-bookworm AS go-build

WORKDIR /build
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download

COPY whatsapp-bridge/ ./

RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/whatsapp-bridge .

# ---------------------------------------------------------- bridge runtime
FROM debian:bookworm-slim AS bridge

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# main.go opens "file:store/messages.db" and "file:store/whatsapp.db" as paths
# relative to the working directory, and writes media under store/<chat-jid>/.
# WORKDIR must therefore be the parent of the mounted store directory.
WORKDIR /app
COPY --from=go-build /out/whatsapp-bridge /usr/local/bin/whatsapp-bridge

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/whatsapp-bridge"]

# ------------------------------------------------------------- mcp runtime
FROM python:3.12-slim-bookworm AS mcp

# ffmpeg transcodes outbound voice notes to Opus (audio.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# uv from PyPI rather than COPY --from=ghcr.io/astral-sh/uv, so the build has
# no cross-registry dependency.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer first so application edits don't invalidate the install.
COPY whatsapp-mcp-server/pyproject.toml whatsapp-mcp-server/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY whatsapp-mcp-server/ ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
ENTRYPOINT ["python", "main.py"]
