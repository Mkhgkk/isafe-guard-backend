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
# ENV LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}

# Install cuDNN (optional but recommended for deep learning)
# Note: You'll need to download cuDNN from NVIDIA's website first
# This requires NVIDIA developer account and acceptance of terms
# COPY cudnn-linux-x86_64-*.tar.gz /tmp/
# RUN tar -xf /tmp/cudnn-linux-x86_64-*.tar.gz -C /usr/local && \
#     rm /tmp/cudnn-linux-x86_64-*.tar.gz

# Verify installation
RUN nvcc --version


# # python
# RUN dnf -y update && \
#     dnf -y install gcc openssl-devel bzip2-devel libffi-devel zlib-devel make wget && \
#     curl -O https://www.python.org/ftp/python/3.9.19/Python-3.9.19.tgz && \
#     tar xvf Python-3.9.19.tgz && \
#     cd Python-3.9.19 && \
#     # ./configure --enable-optimizations && \
#     ./configure --enable-optimizations --with-lzma && \
#     make -j"$(nproc)" && \
#     make altinstall && \
#     cd .. && rm -rf Python-3.9.19 Python-3.9.19.tgz
# RUN alternatives --install /usr/bin/python python /usr/local/bin/python3.9 1 && \
#     alternatives --install /usr/bin/pip pip /usr/local/bin/pip3.9 1

# Install pyenv
# RUN dnf -y install xz xz-devel
RUN dnf -y update && \
    dnf -y install git gcc make zlib-devel bzip2 bzip2-devel ncurses-devel \
    sqlite sqlite-devel readline-devel openssl-devel tk-devel libffi-devel \
    xz xz-devel wget curl && \
    dnf clean all
RUN curl https://pyenv.run | bash

# Set environment variables for pyenv
ENV PATH="/root/.pyenv/bin:/root/.pyenv/shims:/root/.pyenv/plugins/python-build/bin:$PATH"
ENV PYENV_ROOT="/root/.pyenv"

# Ensure the pyenv build environment can find xz-devel
# ENV LDFLAGS="-L/usr/lib64"
# ENV CPPFLAGS="-I/usr/include"

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
        # -D PYTHON3_EXECUTABLE=/usr/local/bin/python3.9 \
        # -D PYTHON3_INCLUDE_DIR=/usr/local/include/python3.9 \
        # -D PYTHON3_LIBRARY=/usr/local/lib/libpython3.9.so \
        # -D PYTHON3_PACKAGES_PATH=/usr/local/lib/python3.9/site-packages \
        # .. && \
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


# RUN dnf -y install  xz-devel 
# RUN pip install backports.lzma
# RUN /usr/local/bin/pip3.9 install backports.lzma

RUN dnf -y install gstreamer1-plugins-bad-freeworld
RUN gst-inspect-1.0 rtmpsink


RUN dnf -y install ffmpeg

COPY . /app

EXPOSE 5000

CMD ["/bin/bash", "-c", "poetry run python src/run.py"]