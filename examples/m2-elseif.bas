CONTRACT ElseIfFixture()
    DIM height = 150
    DIM selected AS CONDITION = ASSERT_HEIGHT_ABSOLUTE(0)
    IF height < 100 THEN
        selected = ASSERT_HEIGHT_ABSOLUTE(100)
    ELSEIF height < 200 THEN
        selected = ASSERT_HEIGHT_ABSOLUTE(200)
    ELSEIF height < 300 THEN
        selected = ASSERT_HEIGHT_ABSOLUTE(300)
    ELSE
        selected = ASSERT_HEIGHT_ABSOLUTE(height)
    END IF
    EMIT selected
END CONTRACT
