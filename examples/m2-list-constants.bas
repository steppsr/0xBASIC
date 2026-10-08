CONTRACT ListConstants()
    CONST groups AS LIST OF LIST OF INTEGER = [[], [7, 20]]
    CONST saved = groups
    DIM heights = FIRST(REST(saved))
    EMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(heights))
    EMIT ASSERT_HEIGHT_ABSOLUTE(LIST_LENGTH(heights))
END CONTRACT
