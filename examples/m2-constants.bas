CONTRACT Constants()
    CONST base AS INTEGER = 10
    CONST height = base * 2
    DIM mutable = height
    mutable = mutable + 5
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    EMIT ASSERT_HEIGHT_ABSOLUTE(mutable)
END CONTRACT
