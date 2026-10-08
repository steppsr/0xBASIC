' Integer arithmetic executes in CLVM; intermediate values can exceed 64 bits.
' Backend fixture only: this contract has no ownership authorization.
CONTRACT IntegerHeight()
    EMIT ASSERT_HEIGHT_ABSOLUTE(2 + 3 * 4)
    EMIT ASSERT_HEIGHT_ABSOLUTE(18446744073709551616 - 18446744073709551615)
    EMIT ASSERT_HEIGHT_ABSOLUTE(-(-128))
END CONTRACT
