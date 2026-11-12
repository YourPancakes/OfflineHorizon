# Optional native-Linux build image. Do not build or run this on a 2 GB / 1 CPU VPS.
# The release_fallback.py resource guard requires at least 6 GiB available
# memory, 18 GiB free storage and 2 CPU cores before docker is invoked.
FROM rust:1.99-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates pkg-config clang cmake build-essential \
    libasound2-dev libudev-dev libx11-dev libxkbcommon-dev \
    libwayland-dev libxi-dev libxrandr-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
