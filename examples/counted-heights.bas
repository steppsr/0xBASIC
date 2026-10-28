CONTRACT CountedHeights()
    FOR height = 5 TO 1 STEP -2
        EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    NEXT height
END CONTRACT
