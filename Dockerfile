FROM fedora:40
LABEL maintainer="emmachalz745@outlook.com"

RUN dnf -y update && \
    dnf -y install \
    gcc \
    gcc-c++ \
    make \
    kernel-devel \
    kernel-headers \
    wget \
    curl \
    git \
    vim \
    dnf-plugins-core \
    kmod \
    elfutils-libelf-devel \
    which \
    procps-ng && \
    dnf clean all

RUN dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/fedora39/x86_64/cuda-fedora39.repo


RUN dnf clean all && dnf -y install cuda-toolkit-12-6

# Set environment variables
ENV PATH=/usr/local/cuda-12.6/bin${PATH:+:${PATH}}


# Verify installation
RUN nvcc --version



RUN dnf -y update && \
    dnf -y install git gcc make zlib-devel bzip2 bzip2-devel ncurses-devel \
    sqlite sqlite-devel readline-devel openssl-devel tk-devel libffi-devel \
    xz xz-devel wget curl && \
    dnf clean all
RUN curl https://pyenv.run | bash

# Set environment variables for pyenv
ENV PATH="/root/.pyenv/bin:/root/.pyenv/shims:/root/.pyenv/plugins/python-build/bin:$PATH"
ENV PYENV_ROOT="/root/.pyenv"

# Install Python 3.9 using pyenv
RUN pyenv install 3.9.19 && pyenv global 3.9.19

# Check if lzma module is available
RUN python -c "import lzma; print('lzma module is available')"

# pygobject
RUN dnf -y install cmake cairo-devel cairo-gobject-devel pkg-config gobject-introspection-devel
RUN pip install pygobject==3.40.0

#gstreamer
RUN dnf -y install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm \
&& dnf -y install \
gstreamer1-devel \
gstreamer1-plugins-base-tools \
gstreamer1-doc \
gstreamer1-plugins-base-devel \
gstreamer1-plugins-good \
gstreamer1-plugins-good-extras \
gstreamer1-plugins-ugly \
gstreamer1-plugins-bad-free \
gstreamer1-plugins-bad-free-devel \
gstreamer1-plugins-bad-free-extras \
gstreamer1-plugin-openh264


RUN dnf -y groupinstall "Development Tools"
RUN pip install --no-cache-dir numpy
RUN curl -sSL https://install.python-poetry.org | python3.9
RUN git clone https://github.com/opencv/opencv.git /opencv && \
    cd /opencv && git checkout 4.10.0
RUN git clone https://github.com/opencv/opencv_contrib.git /opencv_contrib && \
    cd /opencv_contrib && git checkout 4.10.0
COPY pyproject.toml poetry.lock /app/
WORKDIR /app

ENV PATH="/root/.local/bin:$PATH"

RUN set -e \
    && poetry config virtualenvs.create false \
    && poetry install --no-root \
    && poetry run pip uninstall -y opencv-python opencv-python-headless 
RUN ls $PYENV_ROOT/versions
RUN mkdir -p /opencv/build && cd /opencv/build && \
    cmake \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX=/usr/local \
        -D BUILD_opencv_python3=ON \
        -D OPENCV_EXTRA_MODULES_PATH=/opencv_contrib/modules \
        -D BUILD_opencv_freetype=ON \
        -D BUILD_opencv_harfbuzz=ON \
        -D PYTHON3_EXECUTABLE=$PYENV_ROOT/versions/3.9.19/bin/python \
        -D PYTHON3_INCLUDE_DIR=$PYENV_ROOT/versions/3.9.19/include/python3.9 \
        -D PYTHON3_LIBRARY=$PYENV_ROOT/versions/3.9.19/lib/libpython3.9.so \
        -D PYTHON3_PACKAGES_PATH=$PYENV_ROOT/versions/3.9.19/lib/python3.9/site-packages \
        .. && \
    make -j"$(nproc)" && \
    make install && \
    ldconfig && \
    python3.9 -c "import cv2; print('OpenCV version:', cv2.__version__)" && \
    rm -rf /opencv /opencv_contrib

RUN dnf -y install gstreamer1-plugins-bad-freeworld
RUN gst-inspect-1.0 rtmpsink
RUN dnf -y install ffmpeg

COPY . /app

EXPOSE 5000

CMD ["/bin/bash", "-c", "poetry run python src/run.py"]
# CMD ["poetry", "run", "gunicorn", "--bind", "0.0.0.0:5000", "--worker-class", "eventlet", "--workers", "1", "--worker-connections", "2000", "--timeout", "120", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-", "--pythonpath", "src", "wsgi:app"]
