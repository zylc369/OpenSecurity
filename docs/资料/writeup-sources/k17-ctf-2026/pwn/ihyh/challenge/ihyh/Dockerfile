FROM ubuntu:22.04@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc AS chall

WORKDIR /app
COPY flag /
COPY ./chal .

FROM pwn.red/jail
WORKDIR /
COPY --from=chall / /srv

RUN ln -s /app/chal /srv/app/run

ENV JAIL_MEM=50M JAIL_PORT=5000 JAIL_PIDS=10 JAIL_TIME=300 JAIL_TMP_SIZE=10M
