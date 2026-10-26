# FOR/NEXT design proposal

Status: specification-first design checkpoint, 2026-10-25. **Not implemented in released compiler `0.1.0-m3.8b`.** Examples on this page are proposed acceptance inputs, not runnable release examples. The released [language specification](../language-v0.1.md) and [grammar](grammar.ebnf) remain unchanged.

This selects one counted-loop form for the next Core increment. It excludes WHILE/DO, collection iteration syntax, EXIT/CONTINUE, user recursion and modules. Internal generated loop recursion does not permit recursive user functions.

Implementation checkpoint: the [private test-only parser/AST prototype](for-next-parser.md) covers the first syntax slice while preserving all public released behavior. The [private semantic-analysis checkpoint](for-next-analysis.md) adds scope/type checks and carried-local metadata. Executable loop lowering remains the next step.

## Syntax

```basic
FOR index = startExpression TO endExpression [STEP stepExpression]
    statements
NEXT index
```

The square brackets above mark optional syntax, not literal tokens. Proposed token grammar extension:

```ebnf
for_statement = "FOR", IDENT, "=", expression, "TO", expression,
                [ "STEP", expression ], NL, block, "NEXT", IDENT, NL ;
```

Add `for_statement` to statements in contracts and functions. Existing expression precedence, continued-line rules inside delimiters, comments, blank lines and case-insensitive names apply. `NEXT` must name the innermost loop counter, matched case-insensitively. Bare NEXT, comma-separated counters, `END FOR`, and `FOR i AS INTEGER` are not accepted in this increment.

FOR, TO, STEP and NEXT become reserved keywords. They are currently available as ordinary identifiers where not otherwise restricted; this is a source compatibility change, not merely a parser extension. A migration note must instruct affected programs to rename those identifiers.

## Types, scope and snapshots

- Start, end and explicit step must each have type INTEGER. No implicit AMOUNT conversion or numeric BOOLEAN interpretation. Omitted STEP is INTEGER `1`.
- The header declares a fresh INTEGER counter. It is not an assignment to an existing DIM. Apply existing no-shadowing/name rules against visible locals, fixed/solution/function parameters, callable names and built-ins.
- Analyze header expressions in the enclosing scope before introducing the counter. The new counter is unavailable in its own start, end or step expressions.
- The counter is visible inside the body and nested scopes, but not after NEXT. It is read-only: assignment or redeclaration is rejected. Each iteration binds its next value internally.
- Evaluate start, end, then step exactly once, left-to-right, on every entry to the loop statement. Evaluate all three before deciding whether the body runs. A failing earlier expression aborts before later expressions execute.
- Header values are snapshots. Assigning an outer variable used by a header expression does not alter this loop's bound or step. A nested loop evaluates its own header anew on each entry from the outer body.
- Body DIM/CONST declarations are local to the body and do not escape. Their initializers execute whenever control reaches the declaration on an iteration. Assignment to existing outer DIM locals is allowed and carries state to the next iteration and following statements. Other enclosing values remain immutable.

Types of carried locals are fixed by their declarations. INTEGER, BOOLEAN, byte/string/domain values, lists, pairs and CONDITION follow the same assignment rules as outside a loop. A zero-iteration loop leaves all outer locals unchanged. Within a body, statements observe preceding assignments in normal source order.

## Iteration and failures

For evaluated integers `start`, `end` and `step`:

1. If step is zero, abort evaluation with a runtime failure, including when the range would otherwise be empty.
2. Set the internal counter to start.
3. For a positive step, execute the body only while counter <= end. For a negative step, execute it only while counter >= end.
4. After normal body completion, carry updated outer locals/conditions, add step to the counter, and repeat the test.
5. When the test is false, continue after NEXT with the final outer state. The counter is out of scope.

Bounds are inclusive, but an endpoint is visited only if reached by repeated stepping. Equal start/end executes once for any nonzero step. A direction pointing away from the bound executes zero iterations. Arbitrary-precision INTEGER addition prevents machine-width wraparound; integer size and execution cost remain resource constraints.

Zero step is a runtime value failure, E0500 through the local runner. `check` accepts a correctly typed literal zero step; constant folding must preserve failure timing. A zero-step loop in an unselected branch or after a returned path does not execute and must not fail merely because it is statically visible. All unreachable syntax and types remain checked.

An ASSERT failure or failed conversion inside an executed iteration aborts evaluation without returning partial conditions. Skipped bodies do not evaluate their expressions. Header evaluation can fail even for an empty range.

## Conditions and function returns

EMIT remains permitted only in contracts. Conditions are returned in actual execution order: statements before the loop, each visited iteration in sequence, then statements afterward. Nested loops preserve the same ordering. A helper function may return a CONDITION for its caller to emit; it cannot emit directly.

RETURN inside a function loop exits the **function**, not just the loop. It suppresses the remaining body, increment, next-iteration test and all subsequent function statements. Propagate this state through nested loops and conditionals. RETURN remains forbidden in contracts.

For definite-return analysis, treat every loop as potentially executing zero times. A RETURN only inside a loop does not satisfy a function's all-path return requirement, even if literal bounds suggest an iteration. A following RETURN or another independently complete control-flow path is required. This conservative rule avoids adding a separate constant-range proof system.

## Cost, termination and compiler budgets

A nonzero step with immutable finite INTEGER bounds has a finite mathematical iteration count. For a range whose direction permits entry, the count is `floor(abs(end - start) / abs(step)) + 1`; otherwise it is zero. This formula describes semantics, not a new division operator in the language or a requirement to precompute the count.

There is **no new implicit runtime iteration cap** in this design. Runtime headers may come from untrusted solution data; a mathematically finite loop may still exceed any practical cost budget. The local runner retains its explicit cost limit and E0501 behavior. Node/consensus cost limits remain separate. Programs needing an application-specific bound must assert it explicitly before looping.

The baseline backend must generate a reusable loop body, not unroll a runtime range. Source size and code generation work must not scale with the numeric iteration count. Empty loop bodies must still use the loop execution model for this first implementation; range-elimination optimizations are deferred until separately reviewed with cost evidence.

Proposed static guards for this increment are at most 256 syntactic FOR statements per contract or function body and at most 32 simultaneously nested FOR bodies. Counts include loops in untaken branches. These are compiler resource limits, not maximum runtime iterations. Existing IF/expression/local/type/constant limits remain in force. Mixed IF/FOR nesting must also use a shared block-depth budget of 32 to avoid bypassing recursion protection by alternating constructs. Root body depth is zero; entering an IF or FOR body adds one. Existing ELSEIF depth accounting must be preserved and documented in implementation tests.

The existing syntactic EMIT budget remains a source-statement budget; repeated execution of an EMIT does not introduce a new 256-condition runtime rule. Large results remain subject to serialization, display and consensus limits. The existing host result-display failure can occur after VM reduction. See [resource limits](limits-and-failures.md).

Internal compiler/work budgets must charge loop body analysis and carried-type construction, including nested loops. Backend recursion and frame handling need measured stack/allocation tests; do not infer bounded implementation memory solely from mathematical termination or use of a tail-position CLVM call.

## Illustrative acceptance programs

```basic
CONTRACT SumRange(rangeStart AS INTEGER, rangeEnd AS INTEGER)
    DIM total AS INTEGER = 0
    FOR i = rangeStart TO rangeEnd
        total = total + i
    NEXT i
    ASSERT total = 6
END CONTRACT
```

With rangeStart=1 and rangeEnd=3, normal completion returns no conditions. This is an arithmetic fixture, not an authorization contract.

```basic
CONTRACT OrderedHeights()
    FOR h = 5 TO 1 STEP -2
        EMIT ASSERT_HEIGHT_ABSOLUTE(h)
    NEXT h
END CONTRACT
```

Expected raw condition sequence: `((83 5) (83 3) (83 1))`. This illustrates emission order; it does not assert that the conditions imply three different transaction heights.

```basic
FUNCTION FirstPositive(low AS INTEGER, high AS INTEGER) AS INTEGER
    FOR candidate = low TO high
        IF candidate > 0 THEN
            RETURN candidate
        END IF
    NEXT candidate
    RETURN 0
END FUNCTION

CONTRACT FindValue()
    ASSERT FirstPositive(-2, 3) = 1
END CONTRACT
```

## Required acceptance matrix

These are planned checks, not passing results. Each implementation slice must turn its applicable cases into executable tests.

| Area | Cases and expected outcomes |
| --- | --- |
| Range arithmetic | 1..3 default: 1,2,3; 1..6 step 2: 1,3,5; 5..1 step -2: 5,3,1; equal bounds: once; wrong direction: zero |
| Large integers | Bounds beyond signed/unsigned machine widths; no wraparound; huge range rejected by practical VM cost rather than compiler unrolling |
| Zero step | Literal and dynamic zero: E0500 when entered, including empty-looking ranges; no failure in unselected branches |
| Header order | Start failure prevents end/step; end failure prevents step; invalid step evaluated before empty-range decision |
| Snapshot behavior | Body changes outer end/step variables without changing current loop schedule; nested headers use the state at each inner entry |
| Scoping | Counter readable in body, unavailable in header/after NEXT; reject assignment, shadowing and mismatched NEXT; sibling loops may reuse the counter name |
| Syntax/types | Accept case/comments/LF/CRLF/BOM; reject omitted NEXT name, extra counter, unsupported AS syntax, non-INTEGER headers and malformed nesting |
| Carried state | Zero-iteration preservation; sequential multi-local assignments; BOOLEAN, STRING/BYTES, domain, list/pair and CONDITION locals; reinitialized body locals |
| Conditional flow | Conditional outer-local update preserves incoming value on untaken path; skipped body conversion does not fail; executed unused conversion does fail |
| Nested emissions | Exact pre/body/post and nested order; repeat one syntactic EMIT beyond 256 iterations within an adequate cost/result budget; failure returns no partial result |
| Returns | Early return skips remaining work/increment; nested return exits function; loop-only return rejected by definite-return analysis; contract RETURN/function EMIT rejected |
| Raw boundaries | Validate all declared input fields before loop entry, even if loop executes zero times; malformed raw list/scalar values remain rejected |
| Resource guards | At/over syntactic-loop and nesting limits; mixed IF/FOR nesting; existing limits remain enforced; exact VM cost success and cost-minus-one failure |
| Inspection/artifacts | AST spans/loop nodes, typed IR carried values, CLVM inspect/build parity, deterministic Windows/Linux bytes and no-overwrite behavior |
| Compatibility | Current keyword identifiers need migration; original non-loop golden programs retain byte/hash/cost expectations unless an explicit change is justified |
| Spend integration | One representative loop-generated payment/condition scenario with valid and adversarial inputs, exact outputs, and simulator/full-node validation as applicable |

Use a simple independent host-side iteration model for range/state/output expectations and the pinned VM for generated-program execution. Compiler-produced snapshots alone are insufficient. Mathematical step counts and range fixtures must not depend on executing untrusted enormous loops in the test harness.

## Versioning and implementation sequence

Adding syntax and reserving identifiers requires a new compiler version and a recorded language-version decision before the feature becomes externally available. The [activation plan](for-next-activation.md) selects language `0.2` and compiler `0.2.0-alpha.1` for the first public loop-capable implementation; neither identity is active yet. ABI 1 and the pinned VM profile can remain unchanged only if boundary encodings, currying and execution flags are preserved. Update manifest schema constants, version checks, documentation and fixtures together when the language identity changes. Do not modify the existing experimental tag or assets.

Implement in bounded slices:

1. Parser/AST and diagnostics: counter/header/body/NEXT spans, keyword migration, nesting guards and negative syntax cases. Keep execution unavailable until semantic/backend support exists; avoid advertising a partial feature.
2. Analysis and typed loop representation: fresh counter scope, header snapshots, outer-local state, condition ordering and function-return propagation. Preserve existing non-loop behavior.
3. CLVM lowering and execution: runtime step guard, signed bound test, loop body/state transition and return-aware continuation. Validate range/state/failure cases with independent expectations.
4. Integration and compatibility: boundary/CLI/inspection tests, cost/size regressions, Windows then native Linux, followed by applicable spend/full-node cases.
5. Documentation and release: promote the implemented subset into normative language/grammar/ABI/CLI documents, publish exact examples and migration notes, validate source-inclusive packages, then seek approval for a new release.

No native Linux test is required for this design document. Each implementation handoff must provide exact commands and expected outcomes. Parser, semantic analysis, executable contract/function lowering, emission/resource checks and depth/golden fixtures have passed Windows and native Linux testing behind the private gate. The activation plan now governs coordinated public implementation and compatibility changes.
