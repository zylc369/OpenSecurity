# debian:13.4-slim
FROM debian@sha256:4ffb3a1511099754cddc70eb1b12e50ffdb67619aa0ab6c13fcd800a78ef7c7a AS chall

WORKDIR /app
COPY flag /
COPY ./chal .

FROM pwn.red/jail
WORKDIR /
COPY --from=chall / /srv
# note that the link target has no /srv prefix due to the chroot
RUN ln -s /app/chal /srv/app/run
# https://github.com/redpwn/jail?tab=readme-ov-file#configuration-reference
ENV JAIL_MEM=50M JAIL_PORT=5000 JAIL_PIDS=10 JAIL_TIME=300
