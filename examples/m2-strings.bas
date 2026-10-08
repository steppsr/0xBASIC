CONTRACT StringFixture()
    CONST greeting AS STRING = "Hello, Chia!"
    DIM message AS STRING = Echo(greeting)
    ASSERT message = "Hello, Chia!"
    EMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(UTF8(message)))
END CONTRACT

FUNCTION Echo(message AS STRING) AS STRING
    RETURN message
END FUNCTION
