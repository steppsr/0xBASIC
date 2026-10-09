CONTRACT ScalarHeight(enabled AS BOOLEAN, prefix AS BYTES, base AS INTEGER)
    SOLUTION approved AS BOOLEAN
    SOLUTION payload AS BYTES
    DIM flags AS LIST OF BOOLEAN = [enabled, approved]
    DIM data = CONCAT(prefix, payload)
    IF FIRST(flags) AND FIRST(REST(flags)) THEN
        EMIT ASSERT_HEIGHT_ABSOLUTE(base + Size(data))
    END IF
END CONTRACT

FUNCTION Size(data AS BYTES) AS INTEGER
    RETURN BYTE_LENGTH(data)
END FUNCTION
