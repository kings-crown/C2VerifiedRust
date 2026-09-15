#include <stdio.h>

void varargs_demo(void) {
    /* Check format/arg type matching after promotion. */
    printf("%d\n", 0);
    printf("%ld\n", 0L);
}
