CONTRACT BooleanChecks()
    CONST minimum AS INTEGER = 100
    CONST enabled AS BOOLEAN = NOT FALSE
    DIM height = minimum + 20
    DIM ready AS BOOLEAN = height >= minimum
    ASSERT enabled
    ASSERT ready
    EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    ready = height < minimum
    ASSERT NOT ready
END CONTRACT
