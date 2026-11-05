' Isolated test fixture: split six mojos into distinct outputs of 1, 2 and 3.
' Public deterministic harness keys are test-only. Local run does not sign spends.
CONTRACT LoopPayment(owner AS PUBLICKEY, total AS AMOUNT)
    SOLUTION recipient AS PUZZLEHASH
    SOLUTION count AS INTEGER
    ASSERT count >= 1 AND count <= 3
    EMIT ASSERT_MY_AMOUNT(total)
    DIM message AS BYTES = CONCAT(UTF8("0xBASIC/loop-payment/v1"), 0x00)
    message = CONCAT(message, KEY_BYTES(owner))
    message = CONCAT(message, HASH_BYTES(recipient))
    message = CONCAT(message, U64BE(AMOUNT_VALUE(total)))
    message = CONCAT(message, U32BE(count))
    EMIT AGG_SIG_ME(owner, SHA256(message))
    DIM paid AS INTEGER = 0
    FOR amountIndex = 1 TO count
        paid = paid + amountIndex
        EMIT CREATE_COIN(recipient, AS_AMOUNT(amountIndex))
    NEXT amountIndex
    ASSERT paid = AMOUNT_VALUE(total)
END CONTRACT
