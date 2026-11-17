FROM docker.io/debian:trixie

RUN apt update && apt install -y build-essential git pigz wget

# Need recent uftrace (v0.20), which implements:
# - dump --srcline (81fe3b94782)
# - fix for --time-range (5f347b2)
# - add realtime clock option for using with uftrace record (f57c29f)
RUN sed -e 's/Types: deb/Types: deb deb-src/' -i /etc/apt/sources.list.d/debian.sources
RUN apt update && apt build-dep -y uftrace
RUN cd /tmp && git clone https://github.com/namhyung/uftrace && \
cd uftrace && git checkout v0.20 && \
./configure && make -j $(nproc) && make install && rm -rf /tmp/*

RUN apt update && apt install -y libyajl-dev
RUN cd tmp && git clone https://github.com/p-b-o/chrome2fuchsia && \
cd chrome2fuchsia && git checkout 2e7b942 && \
make && mv c2f /usr/bin && rm -rf /tmp/*

RUN apt update && apt install -y black mypy node-typescript
RUN wget -q https://github.com/biomejs/biome/releases/download/@biomejs/biome@2.4.5/biome-linux-x64 && \
mv biome-linux-x64 /usr/bin/biome && chmod +x /usr/bin/biome
