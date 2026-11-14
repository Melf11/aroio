# Build host for Buildroot 2026.02 (the image build needs Linux).
FROM debian:12
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential bc bison flex cpio file git rsync unzip wget curl ca-certificates python3 \
      libssl-dev libncurses-dev perl patch gzip bzip2 xz-utils zstd ccache locales openssl \
    && sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
    && apt-get clean
ENV LANG=en_US.UTF-8 FORCE_UNSAFE_CONFIGURE=1
RUN git config --global --add safe.directory '*'
