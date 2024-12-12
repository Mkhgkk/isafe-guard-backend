# Use the CUDA runtime image instead of the devel image to reduce image size
FROM nvidia/cuda:12.6.0-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/usr/local/nvidia/bin:/usr/local/cuda/bin:${PATH}" \
    LD_LIBRARY_PATH="/usr/local/nvidia/lib:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}"

# Install necessary system packages and build dependencies for Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libgdbm-dev \
    libnss3-dev \
    zlib1g-dev \
    xz-utils \
    git \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    lzma \
    liblzma-dev \
    libbz2-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python 3.9.19
RUN curl -O https://www.python.org/ftp/python/3.9.19/Python-3.9.19.tgz \
    && tar xvf Python-3.9.19.tgz \
    && cd Python-3.9.19 \
    && ./configure --enable-optimizations \
    && make -j$(nproc) \
    && make altinstall \
    && cd .. \
    && rm -rf Python-3.9.19 Python-3.9.19.tgz

# Update alternatives to ensure Python 3.9.19 is the default
RUN update-alternatives --install /usr/bin/python python /usr/local/bin/python3.9 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/local/bin/pip3.9 1

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3.9 - \
    && export PATH="/root/.local/bin:$PATH" \
    && echo "export PATH=\"/root/.local/bin:$PATH\"" >> /etc/profile

# Add Poetry to the PATH for all subsequent commands
ENV PATH="/root/.local/bin:$PATH"

# Copy Poetry files and install dependencies
COPY pyproject.toml poetry.lock /app/
WORKDIR /app
RUN poetry config virtualenvs.create false \
    && poetry install --no-root

# Copy the application code to the container
COPY . /app

# Expose port (change if your app uses a different port)
EXPOSE 5000

# Set the default command to run the application
CMD ["/bin/bash", "-c", "poetry run scripts/convert_models.py && poetry run src/run.py"]
