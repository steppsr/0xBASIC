CONTRACT TextHeight(prefix AS STRING, base AS INTEGER)
    SOLUTION message AS STRING
    DIM copied AS STRING = message
    DIM texts AS LIST OF STRING = [prefix, copied]
    EMIT ASSERT_HEIGHT_ABSOLUTE(base + ByteCount(FIRST(texts)) + ByteCount(FIRST(REST(texts))))
END CONTRACT

FUNCTION ByteCount(text AS STRING) AS INTEGER
    RETURN BYTE_LENGTH(UTF8(text))
END FUNCTION
