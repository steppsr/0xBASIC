' Branch RETURN example, executable since M2-6b2b.
CONTRACT FunctionAnalysis()
    EMIT HeightAt(100, TRUE)
END CONTRACT

FUNCTION HeightAt(height AS INTEGER, enabled AS BOOLEAN) AS CONDITION
    IF enabled THEN
        RETURN MakeHeight(height)
    ELSE
        RETURN MakeHeight(0)
    END IF
END FUNCTION

FUNCTION MakeHeight(height AS INTEGER) AS CONDITION
    RETURN ASSERT_HEIGHT_ABSOLUTE(height)
END FUNCTION
