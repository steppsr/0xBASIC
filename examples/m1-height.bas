' M1 backend fixture: local execution returns ((83 100)).
' Chia spend validation enforces the height; this fixture has no authorization.
CONTRACT HeightFixture()
    EMIT ASSERT_HEIGHT_ABSOLUTE(100)
END CONTRACT
