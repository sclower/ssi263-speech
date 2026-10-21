/* test_sb_host.c -- the C Sounding Board host driven as tools/check_sb_host.py drives src/hosts/soundingboard.py: boot,
 * then each line of text said and run (0.05 s at a time) until the card is idle; every chip write printed as
 * "W <chip time> <reg> <value>", each line's end as "E <writes so far>", and a fault as "FAULT <reason>".
 *
 *     test_sb_host SBLOAD.COM SB.COM "text" ["text" ...]
 */
#include <stdio.h>
#include <stdlib.h>

#include "sb_host.h"

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
    size_t na, nb;
    unsigned char *a, *b;
    sb_host *h;
    const sbh_write *wl;
    int i, k, n, printed = 0;
    if (argc < 4) {
        fprintf(stderr, "usage: test_sb_host SBLOAD.COM SB.COM text...\n");
        return 2;
    }
    a = slurp(argv[1], &na);
    b = slurp(argv[2], &nb);
    h = sbh_create(a, na, b, nb, NULL, 44100.0, err, (int)sizeof err);
    free(a);
    free(b);
    if (!h) {
        printf("FAULT %s\n", err);
        return 1;
    }
    sbh_set_int(h, "log_writes", 1);
    sbh_boot(h, 0.3);
    for (i = 3; i < argc && !sbh_fault(h); i++) {
        const double *y;
        unsigned char line[4096];
        int len = 0;
        while (argv[i][len] && len < (int)sizeof line - 1) {
            line[len] = (unsigned char)argv[i][len];
            len++;
        }
        line[len++] = '\r';                             /* say(text + "\r"), one call */
        sbh_say(h, line, len);
        sbh_run(h, 0.05, 0.0005, &y);
        for (k = 0; k < 2400 && sbh_busy(h, 0.05, 1.5) && !sbh_fault(h); k++)
            sbh_run(h, 0.05, 0.0005, &y);
        n = sbh_writes(h, &wl);
        for (; printed < n; printed++)
            printf("W %.9f %d %02X\n", wl[printed].t, wl[printed].reg, wl[printed].val);
        printf("E %d\n", n);
    }
    if (sbh_fault(h))
        printf("FAULT %s\n", sbh_error(h));
    sbh_destroy(h);
    return 0;
}
