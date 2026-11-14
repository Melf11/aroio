# Build host for Buildroot 2026.02 (the image build needs Linux).
FROM debian:12
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential bc bison flex cpio file git rsync unzip wget ca-certificates python3 \
      libssl-dev libncurses-dev perl patch gzip bzip2 xz-utils zstd ccache \
    && apt-get clean
ENV CCACHE_DIR=/work/.ccache
