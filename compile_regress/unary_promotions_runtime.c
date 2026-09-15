/* Regression: unary +, -, and ~ promote narrow integers to int before use.
 * All arithmetic is representable; these checks do not rely on signed overflow. */
int main(void) {
    unsigned char byte = 255;
    signed char negative_byte = -128;
    unsigned short word = 65535;

    if (+byte != 255 || -byte != -255 || ~byte != -256)
        return 1;
    if (+negative_byte != -128 || -negative_byte != 128 || ~negative_byte != 127)
        return 2;
    if (+word != 65535 || -word != -65535 || ~word != -65536)
        return 3;
    if (sizeof(+byte) != sizeof(int) || sizeof(-negative_byte) != sizeof(int) ||
        sizeof(~word) != sizeof(int))
        return 4;
    return 0;
}
