FROM python:3.14.4-slim-trixie AS chall

RUN apt-get update && apt-get install -y openssh-server vim

# Defang setuid binaries
RUN find / -xdev -perm /4000 -type f -exec chmod a-s {} \; ; true

# Add a user for ssh
RUN adduser --disabled-password --comment "" ctf
RUN echo 'ctf:hunter2' | chpasswd

# Add a user for setuid
RUN adduser --system --group --no-create-home --disabled-password --comment "" admin

COPY --chown=admin:admin flag /
RUN chmod 400 /flag

WORKDIR /app
COPY src/runner src/main.py /app/
RUN chmod +x runner

COPY --chown=ctf:ctf src/client.py /home/ctf/sample_client.py
RUN su -c "ln -s /app/runner /home/ctf/runner" ctf

RUN chown admin:admin -R /app/ && chmod 4555 /app/runner

# Configure default ssh shell as bash
RUN chsh -s /bin/bash ctf

# Configure sshd
RUN echo 'AllowUsers ctf' >> /etc/ssh/sshd_config
RUN ssh-keygen -A

# Set the MOTD
COPY src/motd /etc/motd

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
