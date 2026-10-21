/* test_st_host.c -- the C SmarTalk host driven as tools/check_st_host.py drives src/hosts/smartalk.py: boot (ST_RUN's
 * lines), then each line of text said and run (0.05 s at a time) until the box is idle; every chip write printed as
 * "W <chip time> <reg> <value>", each line's end as "E <writes so far>", and a fault as "FAULT <reason>".  A line
 * "^X" (the two characters) is the host's cancel instead, after 0.4 s of the text before it.
 *
 *     test_st_host S_TALK.EXE "text" ["text" ...]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "st_host.h"

static unsigned char *slurp(const char *path, size_t *n)
{
    FILE *f = fopen(path, "rb");
    unsigned char *d = NULL;
    long len;
    *n = 0;
    if (!f)
        return NULL;
    if (!fseek(f, 0, SEEK_END) && (len = ftell(f)) > 0 && !fseek(f, 0, SEEK_SET)
            && (d = (unsigned char *)malloc((size_t)len)) && fread(d, 1, (size_t)len, f) == (size_t)len)
        *n = (size_t)len;
    fclose(f);
    return d;
}

int main(int argc, char **argv)
{
    char err[256];
    size_t n_exe;
    unsigned char *exe;
    st_host *h;
    const sth_write *wl;
    int i, k, n, printed = 0;
    if (argc < 3) {
        fprintf(stderr, "usage: test_st_host S_TALK.EXE text...\n");
        return 2;
    }
    exe = slurp(argv[1], &n_exe);
    h = sth_create(exe, n_exe, NULL, 44100.0, err, (int)sizeof err);
    free(exe);
    if (!h) {
        printf("FAULT %s\n", err);
        return 1;
    }
    sth_set_int(h, "log_writes", 1);
    sth_boot(h, STH_BOOT_LIMIT);
    for (i = 2; i < argc && !sth_fault(h); i++) {
        const double *y;
        unsigned char line[4096];
        int len = 0;
        if (!strcmp(argv[i], "^X")) {
            sth_cancel(h, 0.6);
        } else {
            while (argv[i][len] && len < (int)sizeof line - 1) {
                line[len] = (unsigned char)argv[i][len];
                len++;
            }
            line[len++] = '\r';                         /* say(text + "\r"), one call */
            sth_say(h, line, len);
            if (i + 1 < argc && !strcmp(argv[i + 1], "^X")) {
                sth_run(h, 0.4, 0.0005, &y);            /* the text before a cancel: 0.4 s of it */
            } else {
                sth_run(h, 0.05, 0.0005, &y);
                for (k = 0; k < 400 && sth_busy(h, 0.05, 1.5) && !sth_fault(h); k++)
                    sth_run(h, 0.05, 0.0005, &y);
            }
        }
        n = sth_writes(h, &wl);
        for (; printed < n; printed++)
            printf("W %.9f %d %02X\n", wl[printed].t, wl[printed].reg, wl[printed].val);
        printf("E %d\n", n);
    }
    if (sth_fault(h))
        printf("FAULT %s\n", sth_error(h));
    sth_destroy(h);
    return 0;
}
