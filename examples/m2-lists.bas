CONTRACT ListFixture()
    DIM values AS LIST OF INTEGER = [1, 2, 3]
    values = []
    DIM nested AS LIST OF LIST OF INTEGER = [[], [1]]
    DIM result = Echo(values)
    EMIT ASSERT_HEIGHT_ABSOLUTE(12)
END CONTRACT

FUNCTION Echo(values AS LIST OF INTEGER) AS LIST OF INTEGER
    IF TRUE THEN
        RETURN values
    END IF
    RETURN []
END FUNCTION
