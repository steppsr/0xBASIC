' Earlier emissions and aliases keep their original values after assignment.
CONTRACT Reassignment()
    DIM height AS INTEGER = 10
    DIM original = height
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    height = height + 5
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    EMIT ASSERT_HEIGHT_ABSOLUTE(original)
END CONTRACT
