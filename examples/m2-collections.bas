CONTRACT CollectionFlow()
    CONST saved AS LIST OF LIST OF INTEGER = [[], [7, 20]]
    DIM bundle = Package(FIRST(REST(saved)))
    EMIT FIRST(FIRST(bundle))
    DIM original = bundle
    IF LIST_LENGTH(FIRST(bundle)) = 2 THEN
        bundle = PAIR(REST(FIRST(bundle)), "remaining")
    ELSE
        bundle = PAIR([], "empty")
    END IF
    EMIT FIRST(FIRST(bundle))
    EMIT ASSERT_HEIGHT_ABSOLUTE(LIST_LENGTH(FIRST(original)))
    ASSERT REST(bundle) = "remaining"
END CONTRACT
FUNCTION Package(heights AS LIST OF INTEGER) AS PAIR OF (LIST OF CONDITION, STRING)
    IF LIST_LENGTH(heights) = 0 THEN
        RETURN PAIR([], "empty")
    END IF
    RETURN PAIR([ASSERT_HEIGHT_ABSOLUTE(FIRST(heights)), ASSERT_HEIGHT_ABSOLUTE(FIRST(REST(heights)))], "ready")
END FUNCTION
