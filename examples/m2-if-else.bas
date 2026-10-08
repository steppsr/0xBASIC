CONTRACT BranchFixture()
    DIM height AS INTEGER = 100
    DIM enabled AS BOOLEAN = TRUE
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    IF enabled AND height >= 100 THEN
        DIM increment = 20
        height = height + increment
        EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    ELSE
        height = 200
    END IF
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
END CONTRACT
