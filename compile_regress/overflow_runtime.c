/* Regression: narrower literal and variable operands must not overflow before
 * conversion to the output width. Each case checks the overflow flag and value
 * against C's defined builtin semantics. */
int main(void) {
    long long wide;
    unsigned long long unsigned_wide;
    int a;
    int b;

    if (__builtin_add_overflow(2147483647, 1, &wide) || wide != 2147483648LL)
        return 1;
    if (__builtin_sub_overflow(-2147483647 - 1, 1, &wide) || wide != -2147483649LL)
        return 2;
    if (__builtin_mul_overflow(65536, 65536, &wide) || wide != 4294967296LL)
        return 3;
    if (__builtin_add_overflow(4294967295U, 1U, &unsigned_wide) ||
        unsigned_wide != 4294967296ULL)
        return 4;
    if (!__builtin_sub_overflow(0U, 1U, &unsigned_wide) ||
        unsigned_wide != 18446744073709551615ULL)
        return 5;
    if (!__builtin_add_overflow(9223372036854775807LL, 1LL, &wide) ||
        wide != (-9223372036854775807LL - 1LL))
        return 6;
    if (!__builtin_mul_overflow(9223372036854775807LL, 2LL, &wide) || wide != -2LL)
        return 7;
    a = 2147483647;
    b = 1;
    if (__builtin_add_overflow(a, b, &wide) || wide != 2147483648LL)
        return 8;
    a = -2147483647 - 1;
    if (__builtin_sub_overflow(a, b, &wide) || wide != -2147483649LL)
        return 9;
    a = 65536;
    b = 65536;
    if (__builtin_mul_overflow(a, b, &wide) || wide != 4294967296LL)
        return 10;
    return 0;
}
