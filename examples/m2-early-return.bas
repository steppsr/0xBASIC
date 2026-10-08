CONTRACT EarlyReturnFixture()
    EMIT HeightAt(100)
END CONTRACT

FUNCTION HeightAt(height AS INTEGER) AS CONDITION
    RETURN ASSERT_HEIGHT_ABSOLUTE(height)
    ' This source is checked, but never executed.
    ASSERT FALSE
    RETURN ASSERT_HEIGHT_ABSOLUTE(-1)
END FUNCTION
