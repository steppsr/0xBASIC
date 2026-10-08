CONTRACT ByteConstantsFixture()
    CONST tag AS BYTES = 0x0001ff
    CONST copy = tag
    CONST matches AS BOOLEAN = copy = 0x0001FF
    ASSERT matches
    ASSERT ChooseTag(TRUE) = tag
    DIM mutable = copy
    mutable = 0x
    ASSERT tag <> mutable
    EMIT ASSERT_HEIGHT_ABSOLUTE(100)
END CONTRACT

FUNCTION ChooseTag(enabled AS BOOLEAN) AS BYTES
    CONST tag = 0x0001ff
    IF enabled THEN
        RETURN tag
    END IF
    RETURN 0x
END FUNCTION
