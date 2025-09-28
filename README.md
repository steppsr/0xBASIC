# 0xBASIC: Build And Script Integrated Contracts

![Logo coming soon]

**Smart Contracts Made Simple with BASIC**

0xBASIC is a programming language designed to simplify smart contract development on the [Chia Blockchain](https://www.chia.net/) by combining the beginner-friendly, BASIC-inspired syntax of QuickBASIC 4.5 with the secure, functional power of CLVM (ChiaLisp Virtual Machine) bytecode. Our mission is to make blockchain programming accessible to developers, hobbyists, and students, enabling everyone to create robust smart contracts for decentralized finance (DeFi), tokenized assets, and more—without wrestling with complex paradigms.

> **Status**: 0xBASIC is in **pre-alpha** development. We're just getting started, and we welcome contributors to help shape the future of Chia smart contracts! Join us to build a language that democratizes blockchain development.

## Why 0xBASIC?

0xBASIC stands for **Build And Script Integrated Contracts**, blending the simplicity of BASIC with Chia's eco-friendly blockchain. Key features include:

- **Familiar Syntax**: Modern BASIC-inspired constructs (e.g., `IF`, `FOR`, `FUNCTION`) without outdated elements like line numbers, making it intuitive for imperative programmers.
- **Direct CLVM Compilation**: Compiles `.xb` source files to efficient CLVM bytecode, ensuring full compatibility with Chia's functional, immutable execution model.
- **Blockchain-Native Operations**: Built-in support for coin creation (`CREATE_COIN`), assertions (`ASSERT_MY_COIN_ID`), and cryptographic functions (`BLS_VERIFY`, `SHA256`).
- **Functional Simplicity**: Exposes CLVM's functional programming (e.g., `CONS`, `MAP`) through approachable BASIC syntax.
- **Cross-Platform**: Runs on Windows, macOS, and Linux.
- **Open-Source**: Licensed under Apache 2.0, encouraging community contributions.

Whether you're a seasoned developer or new to blockchain, 0xBASIC empowers you to create secure, deterministic smart contracts with ease.

## Example: Payment Puzzle

Here's a sample 0xBASIC program demonstrating a payment smart contract (syntax subject to refinement):

```basic
MODULE PaymentPuzzle(RECIPIENT_HASH AS PUZZLEHASH, MIN_AMOUNT AS INTEGER)
    INCLUDE "condition_codes.clib"
    
    FUNCTION MakePayment(amount AS INTEGER, signature AS G2ELEMENT, memo AS BYTES) AS LIST
        DIM conditions AS LIST
        DIM messageHash AS BYTES
        
        ' Validate inputs
        ASSERT amount > 0, "Amount must be positive"
        ASSERT amount >= MIN_AMOUNT, "Amount below minimum"
        ASSERT STRLEN(RECIPIENT_HASH) = 32, "Invalid recipient hash"
        
        ' Create message for signature
        messageHash = SHA256(RECIPIENT_HASH, amount, memo)
        
        ' Build conditions
        conditions = LIST(
            CREATE_COIN(RECIPIENT_HASH, amount, LIST(memo)),
            AGG_SIG_UNSAFE(PUBKEY_FOR_EXP(1), messageHash),
            ASSERT_MY_AMOUNT(amount)
        )
        
        MakePayment = conditions
    END FUNCTION
END MODULE
