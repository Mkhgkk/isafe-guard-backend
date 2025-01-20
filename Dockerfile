FROM nvidia/cuda:12.6.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

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
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-alsa \
    gstreamer1.0-pulseaudio \
    gstreamer1.0-gl \
    python3-gi \
    cmake \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libfreetype6-dev \
    libharfbuzz-dev \
    libopenblas-dev \
    liblapack-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libeigen3-dev \
    libgflags-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -O https://www.python.org/ftp/python/3.9.19/Python-3.9.19.tgz && \
    tar xvf Python-3.9.19.tgz && \
    cd Python-3.9.19 && \
    ./configure --enable-optimizations && \
    make -j"$(nproc)" && \
    make altinstall && \
    cd .. && rm -rf Python-3.9.19 Python-3.9.19.tgz

RUN update-alternatives --install /usr/bin/python python /usr/local/bin/python3.9 1 && \
    update-alternatives --install /usr/bin/pip pip /usr/local/bin/pip3.9 1

RUN pip install --no-cache-dir numpy

RUN curl -sSL https://install.python-poetry.org | python3.9

RUN git clone https://github.com/opencv/opencv.git /opencv && \
    cd /opencv && git checkout 4.10.0
RUN git clone https://github.com/opencv/opencv_contrib.git /opencv_contrib && \
    cd /opencv_contrib && git checkout 4.10.0


COPY pyproject.toml poetry.lock /app/
WORKDIR /app

RUN poetry config virtualenvs.create false \
    && poetry install --no-root \
    && poetry run pip uninstall -y opencv-python opencv-python-headless || true

RUN mkdir -p /opencv/build && cd /opencv/build && \
    cmake \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX=/usr/local \
        -D BUILD_opencv_python3=ON \
        -D OPENCV_EXTRA_MODULES_PATH=/opencv_contrib/modules \
        -D BUILD_opencv_freetype=ON \
        -D BUILD_opencv_harfbuzz=ON \
        -D PYTHON3_EXECUTABLE=/usr/local/bin/python3.9 \
        -D PYTHON3_INCLUDE_DIR=/usr/local/include/python3.9 \
        -D PYTHON3_LIBRARY=/usr/local/lib/libpython3.9.so \
        -D PYTHON3_PACKAGES_PATH=/usr/local/lib/python3.9/site-packages \
        .. && \
    make -j"$(nproc)" && \
    make install && \
    ldconfig && \
    python3.9 -c "import cv2; print('OpenCV version:', cv2.__version__)" && \
    rm -rf /opencv /opencv_contrib

COPY . /app

EXPOSE 5000

CMD ["/bin/bash", "-c", "poetry run python src/run.py"]


