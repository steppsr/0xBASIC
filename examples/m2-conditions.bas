CONTRACT ConditionLocals()
    DIM height AS INTEGER = 100
    DIM pending AS CONDITION = ASSERT_HEIGHT_ABSOLUTE(height)
    DIM original = pending
    height = height + 20
    EMIT pending
    pending = ASSERT_HEIGHT_ABSOLUTE(height)
    EMIT pending
    EMIT original
END CONTRACT
