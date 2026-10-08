CONTRACT ByteFixture()
    DIM original AS BYTES = 0x0001ff
    DIM selected = ChooseBytes(original, TRUE)
    ASSERT selected = 0x0001FF
    ASSERT selected <> 0x01ff
    EMIT ASSERT_HEIGHT_ABSOLUTE(100)
END CONTRACT

FUNCTION ChooseBytes(value AS BYTES, enabled AS BOOLEAN) AS BYTES
    IF enabled THEN
        RETURN value
    END IF
    RETURN 0x
END FUNCTION
