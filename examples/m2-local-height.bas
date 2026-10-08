' INTEGER locals, inferred types, and case-insensitive name references.
' Backend fixture only; no ownership authorization.
CONTRACT LocalHeight()
    DIM base AS INTEGER = 10
    DIM height = base + 5
    EMIT ASSERT_HEIGHT_ABSOLUTE(HEIGHT)
    DIM later AS INTEGER = height * 2
    EMIT ASSERT_HEIGHT_ABSOLUTE(later)
END CONTRACT
