FROM debian@sha256:1d3c811171a08a5adaa4a163fbafd96b61b87aa871bbc7aa15431ac275d3d430 AS chall

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
