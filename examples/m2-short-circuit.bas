CONTRACT ShortCircuit()
    CONST enabled AS BOOLEAN = TRUE
    DIM height = 120
    DIM ready = enabled AND (height >= 100 AND height < 200)
    ASSERT ready OR height = 0
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
END CONTRACT
