CONTRACT FunctionFixture()
    EMIT HeightAt(100, TRUE)
    EMIT HeightAt(100, FALSE)
END CONTRACT

FUNCTION HeightAt(height AS INTEGER, enabled AS BOOLEAN) AS CONDITION
    DIM selected = 0
    IF enabled THEN
        selected = height
    END IF
    RETURN MakeHeight(selected)
END FUNCTION

FUNCTION MakeHeight(height AS INTEGER) AS CONDITION
    RETURN ASSERT_HEIGHT_ABSOLUTE(height)
END FUNCTION
