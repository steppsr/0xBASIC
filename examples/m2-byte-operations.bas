CONTRACT ByteOperationsFixture()
    CONST prefix AS BYTES = 0x0001
    DIM payload = JoinPayload(prefix, 0x80ff)
    ASSERT payload = 0x000180ff
    ASSERT BYTE_LENGTH(payload) = 4
    EMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(payload))
END CONTRACT

FUNCTION JoinPayload(prefix AS BYTES, suffix AS BYTES) AS BYTES
    RETURN CONCAT(prefix, suffix)
END FUNCTION
