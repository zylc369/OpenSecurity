#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <errno.h>
#include <string.h>

#define MAIN_PATH "/mnt/d/.dev/.competitions/.ctf/K17 CTF 2026/misc/spot/challenge/spot/src/main.py"

void close_fd_not_3_4(int fd) {
    if (fd != 3 && fd != 4) close(fd);
}

int main(int argc, char *argv[], char *envp[])
{
    if (argc < 2)
    {
        fputs("Error: client path not provided.\n", stderr);
        exit(1);
    }
    char *client_path = argv[1];

    int write_pipe[2]; // main -> client
    int read_pipe[2];  // main <- client

    if (pipe(write_pipe) == -1)
    {
        perror("pipe write_pipe failed");
        exit(1);
    }
    if (pipe(read_pipe) == -1)
    {
        perror("pipe read_pipe failed");
        exit(1);
    }

    pid_t main_pid = fork();
    if (main_pid == -1)
    {
        perror("fork for main failed");
        exit(1);
    }

    if (main_pid == 0)
    {   // child (main)
        if (dup2(read_pipe[0], 3) == -1)
        {
            perror("main dup2 for fd 3 failed");
            exit(1);
        }
        if (dup2(write_pipe[1], 4) == -1)
        {
            perror("main dup2 for fd 4 failed");
            exit(1);
        }

        // close original pipe fds
        close_fd_not_3_4(write_pipe[0]);
        close_fd_not_3_4(write_pipe[1]);
        close_fd_not_3_4(read_pipe[0]);
        close_fd_not_3_4(read_pipe[1]);

        // run main (privileged)
        char *envp[] = {NULL};
        execle("/usr/bin/python3", "python", MAIN_PATH, NULL, envp);
        perror("execle main failed");
        exit(1);
    }
    else
    {   // parent
        uid_t real_uid = getuid();

        pid_t client_pid = fork();
        if (client_pid == -1)
        {
            perror("fork for client failed");
            exit(1);
        }

        if (client_pid == 0)
        {   // 2nd child (client)
            if (dup2(write_pipe[0], 3) == -1)
            {
                perror("client dup2 for fd 3 failed");
                exit(1);
            }
            if (dup2(read_pipe[1], 4) == -1)
            {
                perror("client dup2 for fd 4 failed");
                exit(1);
            }

            // close original pipe fds
            close_fd_not_3_4(write_pipe[0]);
            close_fd_not_3_4(write_pipe[1]);
            close_fd_not_3_4(read_pipe[0]);
            close_fd_not_3_4(read_pipe[1]);

            // drop privs
            if (setresuid(real_uid, real_uid, real_uid) == -1)
            {
                perror("setresuid failed");
                exit(1);
            }

            // run client
            char *envp[] = {NULL};
            execle("/usr/bin/python3", "python", client_path, NULL, envp);
            perror("execle client failed");
            exit(1);
        }
        else
        {   // parent
            close(write_pipe[0]);
            close(write_pipe[1]);
            close(read_pipe[0]);
            close(read_pipe[1]);

            int main_status, client_status;
            waitpid(main_pid, &main_status, 0);
            waitpid(client_pid, &client_status, 0);

            if (main_status) exit(1);
            exit(client_status ? 2 : 0);
        }
    }

    return 0;
}
